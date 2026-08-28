import 'dart:async';
import 'dart:developer' as developer;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../services/connectivity_monitor.dart';
import '../services/gateway_api.dart';
import '../services/local_queue_repository.dart';
import 'background_bridge.dart' show BackgroundBridge, backgroundServiceChannelName;
import 'gateway_loop.dart';
import 'interactive_ussd_runner.dart';
import 'sms_service.dart';
import 'ussd_step_event.dart';

/// 20s: comfortably under both TRANSACTION_ENGINE.TIMEOUT_SECONDS and
/// GATEWAY_MANAGER.HEARTBEAT_STALE_SECONDS (90s each, see backend
/// settings.py) - a heartbeat this frequent never lets the gateway's
/// telemetry go stale enough to drop out of eligible_sims(), and a pending
/// task is never queued locally for long before its first dial attempt.
const _tickInterval = Duration(seconds: 20);

/// Stabilisation RC1 (priorité moyenne n°9) : borne haute du backoff
/// progressif ci-dessous - au-delà, on ne fait plus qu'une tentative toutes
/// les 5 minutes tant que le backend reste injoignable, plutôt que de
/// marteler un service en panne toutes les 20s indéfiniment.
const _maxBackoff = Duration(minutes: 5);

/// The second Dart entry point, executed by the headless [FlutterEngine]
/// [GatewayForegroundService] creates - entirely separate from `main()` in
/// `lib/main.dart`, which keeps driving the UI engine as before. Must be
/// annotated `@pragma('vm:entry-point')` or Dart's tree shaker/AOT compiler
/// would strip it as unreachable (nothing in `main()`'s call graph ever
/// calls this function directly - only native code does, by name).
///
/// Stabilisation RC1 (priorité critique n°1) : stopper l'Android
/// `Service` (`stopService()`/`onDestroy()`) ne tue jamais ce `FlutterEngine`
/// headless ni son isolate - c'est voulu, pour ne pas repayer le coût de
/// démarrage à chaque relance (voir GatewayForegroundService, qui garde
/// l'engine en cache). Mais cela signifiait qu'appuyer sur "Arrêter" ne
/// faisait que retirer la notification : ce `Timer.periodic` continuait de
/// tourner indéfiniment. Le correctif : le même `MethodChannel` déjà utilisé
/// par [BackgroundBridge]/[SmsService] pour appeler le natif sert maintenant
/// aussi dans l'autre sens - `GatewayForegroundService.stop()` envoie un
/// message "stop" que ce point d'entrée écoute ici pour annuler le minuteur.
@pragma('vm:entry-point')
void gatewayServiceMain() {
  WidgetsFlutterBinding.ensureInitialized();

  final bridge = BackgroundBridge();
  final sms = SmsService();
  final api = GatewayApi();
  final queue = LocalQueueRepository();
  final loop = GatewayLoop(
    api: api,
    queue: queue,
    dialUssd: bridge.dialUssd,
    deviceInfoProvider: bridge.getTelemetry,
    // Only the headless engine's loop instance gets these - see
    // GatewayLoop's class doc on why the manual-button instance never does.
    dispatchSms: ({required taskId, required phone, required message}) =>
        sms.dispatch(taskId: taskId, phone: phone, message: message),
    drainSmsOutcomes: sms.drainOutcomes,
  );
  // Phase D4.3: an entirely separate async chain from `loop`/`tick()` below
  // - started fire-and-forget (unawaited), never inside the `ticking`
  // reentrancy guard, so a long interactive USSD session never delays a
  // single heartbeat (see the D4 design report on why this must not be
  // `await interactiveSession()` inside the tick chain).
  final interactiveRunner = InteractiveUssdRunner(api: api, queue: queue, bridge: bridge);
  // Phase D4 (reprise après redémarrage/reboot) : si le processus précédent
  // est mort au milieu d'une session interactive (crash, reboot, "Forcer
  // l'arrêt"), UssdAccessibilityService (même processus) est mort avec lui -
  // il n'existe donc aucun moyen fiable de savoir ce que l'écran USSD a fait
  // après coup. On ne devine jamais un résultat ici : seul le verrou LOCAL
  // (`interactive_session`) est levé, pour ne pas bloquer indéfiniment tout
  // futur créneau interactif sur cette Gateway. Le TransactionAttempt côté
  // Backend reste la source de vérité - c'est son propre mécanisme d'expiration
  // (TRANSACTION_ENGINE.TIMEOUT_SECONDS / release_expired(), déjà la voie
  // normale pour une Gateway qui disparaît en cours de tâche) qui le récupère.
  unawaited(_recoverOrphanedInteractiveSession(queue));

  int? gatewayId;
  Timer? timer;
  // Set the instant the native "stop" call is received - checked both
  // before scheduling a new tick and at the very top of tick() itself, so a
  // tick already in flight when "stop" arrives is allowed to finish
  // cleanly (never aborted mid-write to the local queue) but no further
  // tick ever starts afterwards.
  var stopped = false;
  // Stabilisation RC1 (priorité haute n°4) : un runOnce() qui dépasse 20s
  // (backend lent, réseau capricieux) ne doit jamais chevaucher le suivant -
  // deux ticks concurrents liraient/écriraient la même LocalQueueRepository
  // sqflite et pourraient composer le même identifiant de tâche deux fois
  // avant que l'un des deux ait eu le temps de marquer la ligne "dialing".
  // Un tick qui arrive pendant qu'un autre tourne encore est simplement
  // ignoré : le suivant, 20s plus tard, reprendra là où le précédent s'est
  // arrêté, sans perte de tâche (la file locale est le vrai état, pas la
  // mémoire de cette fonction).
  var ticking = false;
  // Stabilisation RC1 (priorité moyenne n°9) : sans ceci, un backend indisponible
  // fait marteler `loop.runOnce()` (donc l'API de paiement/USSD en amont) toutes
  // les 20s indéfiniment. `nextAttemptAt` retarde la prochaine tentative
  // réelle après chaque échec, en croissance géométrique jusqu'à [_maxBackoff] ;
  // `reportAlive()` (purement local, voir BackgroundBridge) continue de
  // tourner à chaque tick sans condition, donc le watchdog ne confond jamais
  // "backend en panne" avec "boucle Dart morte".
  var consecutiveFailures = 0;
  DateTime? nextAttemptAt;

  Duration backoffFor(int failures) {
    final multiplier = 1 << failures.clamp(0, 10);
    final seconds = (_tickInterval.inSeconds * multiplier).clamp(0, _maxBackoff.inSeconds);
    return Duration(seconds: seconds);
  }

  /// Phase D4.3: hands the next interactive task (if any, and if none is
  /// already running) to [interactiveRunner]. `markInteractiveHandedOff`'s
  /// conditional UPDATE (`WHERE state = 'pending_dial'`) is what makes this
  /// safe against an overlapping call - only one caller ever successfully
  /// claims a given row. Declared before [tick] (which references it) since
  /// Dart does not allow a local function to be referenced, even from a
  /// nested closure, before its own declaration.
  Future<void> maybeStartInteractiveSession() async {
    if (interactiveRunner.isRunning) return;
    final task = await queue.nextInteractiveTaskToStart();
    if (task == null) return;
    final attemptId = task.attemptId;
    if (attemptId == null) {
      // Malformed/unexpected: an interactive row without attempt_id can
      // never run the step protocol - drop it rather than retry it forever.
      await queue.markInteractiveHandedOff(task.id);
      return;
    }
    final claimed = await queue.markInteractiveHandedOff(task.id);
    if (!claimed) return; // a concurrent check already took it
    await interactiveRunner.start(
      transactionReference: task.reference,
      attemptId: attemptId,
      ussdCode: task.ussdCode,
      simSlot: task.simSlot,
    );
  }

  // [force]: a fresh reconnect (see ConnectivityMonitor below) is new
  // information worth retrying on immediately, even mid-backoff - it does
  // not, by itself, guarantee the backend is reachable again, but there is
  // no reason to keep waiting out a timer set before the network came back.
  Future<void> tick({bool force = false}) async {
    if (stopped || ticking) return;
    ticking = true;
    if (force) nextAttemptAt = null;
    final now = DateTime.now();
    if (nextAttemptAt == null || !now.isBefore(nextAttemptAt!)) {
      try {
        final result = await loop.runOnce(gatewayId: gatewayId);
        gatewayId = result.status.id;
        consecutiveFailures = 0;
        nextAttemptAt = null;
        final busy = result.pendingFetched > 0 || result.smsFetched > 0;
        await bridge.updateNotification(
          busy
              ? '${result.dialed} composée(s), ${result.smsDispatched} SMS envoyé(s)'
              : 'En veille - ${result.status.heartbeatStatus}',
        );
      } catch (_) {
        // Best-effort: never let a transient failure (offline, backend
        // hiccup) crash the isolate - see reportAlive() below, which fires
        // regardless of this outcome. The next real attempt is delayed by
        // the backoff computed here rather than retried next tick.
        consecutiveFailures++;
        final backoff = backoffFor(consecutiveFailures);
        nextAttemptAt = DateTime.now().add(backoff);
        try {
          await bridge.updateNotification('Backend injoignable - nouvel essai dans ${backoff.inSeconds}s');
        } catch (_) {}
      }
    }
    try {
      await bridge.reportAlive();
    } catch (_) {
      // If even this fails, the platform side is in trouble - the watchdog
      // will notice via the stale timestamp and restart the service.
    } finally {
      ticking = false;
    }
    // Deliberately outside the `ticking` guard and never awaited: starting
    // an interactive session must not delay this tick's completion, nor
    // should a session already running block future ticks from firing.
    unawaited(maybeStartInteractiveSession());
  }

  // Stabilisation RC1 (priorité haute n°7) : jusqu'ici seul `main.dart` (le
  // moteur UI, actif uniquement écran allumé) réagissait à une reconnexion
  // immédiate - la boucle autonome, elle, attendait bêtement le prochain
  // tick des 20s comme n'importe quel autre cycle. Sans grand risque
  // pratique (20s reste court), mais un vrai gain en cas de reconnexion
  // juste après un tick : jusqu'à 20s de latence évitable avant qu'une
  // tâche fraîchement en attente ne soit composée. `tick()` respecte déjà
  // la garde de réentrance (`ticking`) : un reconnect qui tombe pendant un
  // tick déjà en cours est simplement ignoré, sans double exécution.
  final connectivityMonitor = ConnectivityMonitor();
  connectivityMonitor.start();
  connectivityMonitor.onReconnected.listen((_) => tick(force: true));

  // Incoming half of the bridge: GatewayForegroundService.requestStop()
  // (native) calls invokeMethod("stop", ...) on this same channel name: a
  // MethodChannel is bidirectional, and nothing before this fix ever
  // registered a handler for the native-to-Dart direction.
  const controlChannel = MethodChannel(backgroundServiceChannelName);
  controlChannel.setMethodCallHandler((call) async {
    if (call.method == 'stop') {
      stopped = true;
      timer?.cancel();
      await connectivityMonitor.dispose();
    } else if (call.method == 'ussdStepEvent') {
      // Phase D4.2: GatewayForegroundService forwards every
      // UssdAccessibilityService event here - this is the ONLY handler
      // registered for this channel name, so it must dispatch every
      // incoming method, not just "stop" (see BackgroundBridge's doc on
      // why a second setMethodCallHandler() elsewhere would silently
      // replace this one instead of adding to it).
      final args = call.arguments;
      if (args is Map) {
        bridge.emitUssdStepEvent(UssdStepEvent.fromChannelMap(args));
      }
    }
    return null;
  });

  unawaited(tick());
  timer = Timer.periodic(_tickInterval, (_) => tick());
}

/// See the call site's comment in [gatewayServiceMain]. Top-level (not a
/// local closure) so it can be unit-tested directly against a real in-memory
/// [LocalQueueRepository] without spinning up the whole entrypoint.
Future<void> _recoverOrphanedInteractiveSession(LocalQueueRepository queue) async {
  final orphaned = await queue.currentInteractiveSession();
  if (orphaned == null) return;
  developer.log(
    'Clearing orphaned interactive_session (attempt ${orphaned.attemptId}, '
    'reference ${orphaned.transactionReference}) left over from a previous run',
    name: 'gatewayServiceMain',
  );
  await queue.closeInteractiveSession();
}
