import 'dart:developer' as developer;

import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

import 'gateway_api.dart' show PendingTransaction, SmsPendingTask;

/// Lifecycle of one locally-queued USSD task. Deliberately five states, not
/// three - the boundary between `dialing`/`dialed` and `dialed`/`reporting`
/// is exactly where the "dial at most once, retry only the report" rule
/// gets enforced (see [LocalQueueRepository]'s class doc).
class TaskState {
  static const pendingDial = 'pending_dial';
  static const dialing = 'dialing';
  static const dialed = 'dialed';
  static const reporting = 'reporting';
  static const done = 'done';
}

class TransactionTask {
  const TransactionTask({
    required this.id,
    required this.reference,
    required this.transactionType,
    required this.recipientPhone,
    required this.amount,
    required this.ussdCode,
    required this.state,
    this.simSlot,
    this.operator,
    this.dialSuccess,
    this.dialResult,
    this.reportAttempts = 0,
    this.lastReportError,
    this.isInteractive = false,
    this.attemptId,
  });

  final int id;
  final String reference;
  final String transactionType;
  final String recipientPhone;
  final double amount;
  final String ussdCode;
  final int? simSlot;
  // Phase D audit (Critique): the operator expected for this task's SIM -
  // see PendingTransaction.operator's doc. Null skips the native
  // cross-check entirely (older enqueue, or the backend never sent one).
  final String? operator;
  final String state;
  final bool? dialSuccess;
  final String? dialResult;
  final int reportAttempts;
  final String? lastReportError;
  // Phase D4.3: routes this row to the interactive session runner instead
  // of _drainDial()/dialUssd() - see PendingTransaction.isInteractive.
  final bool isInteractive;
  final int? attemptId;

  factory TransactionTask.fromRow(Map<String, Object?> row) {
    return TransactionTask(
      id: row['id'] as int,
      reference: row['reference'] as String,
      transactionType: row['transaction_type'] as String? ?? '',
      recipientPhone: row['recipient_phone'] as String? ?? '',
      amount: (row['amount'] as num?)?.toDouble() ?? 0,
      ussdCode: row['ussd_code'] as String,
      simSlot: row['sim_slot'] as int?,
      operator: row['operator'] as String?,
      state: row['state'] as String,
      dialSuccess: row['dial_success'] == null
          ? null
          : (row['dial_success'] as int) == 1,
      dialResult: row['dial_result'] as String?,
      reportAttempts: row['report_attempts'] as int? ?? 0,
      lastReportError: row['last_report_error'] as String?,
      isInteractive: (row['is_interactive'] as int?) == 1,
      attemptId: row['attempt_id'] as int?,
    );
  }
}

/// Lifecycle of one locally-queued SMS task. Two extra states relative to
/// [TaskState] reflect that an SMS outcome arrives asynchronously (via the
/// native sent/delivered BroadcastReceivers' outbox, see
/// `TelephonyGateway.sendSms`'s doc) rather than as a direct callback like
/// USSD: `sending` can sit unresolved for a while until a later tick's
/// outbox drain reconciles it into `sent_result_known`.
class SmsTaskState {
  static const pendingSend = 'pending_send';
  static const sending = 'sending';
  static const sentResultKnown = 'sent_result_known';
  static const reporting = 'reporting';
  static const done = 'done';
}

class SmsQueueTask {
  const SmsQueueTask({
    required this.id,
    required this.serverId,
    required this.phoneNumber,
    required this.message,
    required this.purpose,
    required this.state,
    this.sendSuccess,
    this.sendResult,
    this.reportAttempts = 0,
    this.lastReportError,
  });

  final int id;
  final int serverId;
  final String phoneNumber;
  final String message;
  final String purpose;
  final String state;
  final bool? sendSuccess;
  final String? sendResult;
  final int reportAttempts;
  final String? lastReportError;

  factory SmsQueueTask.fromRow(Map<String, Object?> row) {
    return SmsQueueTask(
      id: row['id'] as int,
      serverId: row['server_id'] as int,
      phoneNumber: row['phone_number'] as String? ?? '',
      message: row['message'] as String? ?? '',
      purpose: row['purpose'] as String? ?? '',
      state: row['state'] as String,
      sendSuccess: row['send_success'] == null
          ? null
          : (row['send_success'] as int) == 1,
      sendResult: row['send_result'] as String?,
      reportAttempts: row['report_attempts'] as int? ?? 0,
      lastReportError: row['last_report_error'] as String?,
    );
  }
}

/// Phase D2 (moteur USSD interactif) - the one row (if any) representing a
/// currently-active interactive USSD session. Reconstructed straight from
/// the `interactive_session` table - see [LocalQueueRepository]'s class doc
/// for why that table can only ever hold a single row.
class InteractiveSession {
  const InteractiveSession({
    required this.transactionReference,
    required this.attemptId,
    required this.pendingEvent,
    required this.pendingIdempotencyKey,
    required this.pendingPayload,
    this.lastResponse,
    required this.createdAt,
    required this.updatedAt,
  });

  final String transactionReference;
  final int attemptId;
  final String pendingEvent;
  final String pendingIdempotencyKey;
  final String pendingPayload;
  final String? lastResponse;
  final String createdAt;
  final String updatedAt;

  factory InteractiveSession.fromRow(Map<String, Object?> row) {
    return InteractiveSession(
      transactionReference: row['transaction_reference'] as String,
      attemptId: row['attempt_id'] as int,
      pendingEvent: row['pending_event'] as String,
      pendingIdempotencyKey: row['pending_idempotency_key'] as String,
      pendingPayload: row['pending_payload'] as String,
      lastResponse: row['last_response'] as String?,
      createdAt: row['created_at'] as String,
      updatedAt: row['updated_at'] as String,
    );
  }
}

/// Local queue + journal for USSD tasks (Phase C autonomy). The single
/// invariant everything else here exists to protect: **a USSD code is
/// composed at most once, ever, per task.** Only the *reporting* of an
/// already-known outcome to the backend may be retried - re-dialing after an
/// interruption risks a double transfer of real money. See
/// [recoverInterruptedDials] for how a crash/kill mid-dial is handled.
///
/// Deliberately backed by sqflite (not shared_preferences/Hive): the drain
/// loop needs "give me every row still awaiting X" as a plain query, not a
/// manual scan of an in-memory list rebuilt from a single JSON blob.
class LocalQueueRepository {
  LocalQueueRepository({DatabaseFactory? databaseFactory, String? path})
    : _databaseFactory = databaseFactory,
      _path = path;

  final DatabaseFactory? _databaseFactory;
  final String? _path;
  Database? _db;

  Future<Database> get _database async {
    final existing = _db;
    if (existing != null) return existing;
    final factory = _databaseFactory ?? databaseFactory;
    final dbPath = _path ?? p.join(await factory.getDatabasesPath(), 'gateway_queue.db');
    final opened = await factory.openDatabase(
      dbPath,
      options: OpenDatabaseOptions(
        version: 4, onConfigure: _onConfigure, onCreate: _onCreate, onUpgrade: _onUpgrade,
      ),
    );
    _db = opened;
    return opened;
  }

  /// Stabilisation RC1 (priorité haute n°5) : le moteur UI (`main.dart`) et
  /// le moteur headless (`gateway_service_entrypoint.dart`) sont deux
  /// `FlutterEngine` distincts - chacun avec sa propre instance du plugin
  /// sqflite - qui ouvrent le MÊME fichier `gateway_queue.db` depuis le même
  /// processus Android. En mode journal par défaut (rollback journal),
  /// SQLite pose un verrou exclusif pendant toute écriture : une des deux
  /// connexions peut alors essuyer un `SQLITE_BUSY` immédiat si l'autre
  /// écrit au même instant. Le mode WAL autorise un rédacteur et un nombre
  /// illimité de lecteurs en parallèle sans ce verrou exclusif, et
  /// `busy_timeout` fait qu'un conflit écriture/écriture restant (rare, deux
  /// transactions qui écrivent réellement au même instant) attend jusqu'à
  /// 5s au lieu d'échouer tout de suite. Sans effet sur les tests
  /// `sqflite_common_ffi` en base `:memory:` : SQLite y ignore silencieusement
  /// la demande de WAL (non supporté en mémoire) et reste en mode par défaut.
  Future<void> _onConfigure(Database db) async {
    await db.rawQuery('PRAGMA journal_mode=WAL');
    await db.execute('PRAGMA busy_timeout=5000');
  }

  Future<void> _onCreate(Database db, int version) async {
    await db.execute('''
      CREATE TABLE transaction_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT NOT NULL UNIQUE,
        transaction_type TEXT,
        recipient_phone TEXT,
        amount REAL,
        ussd_code TEXT NOT NULL,
        sim_slot INTEGER,
        operator TEXT,
        state TEXT NOT NULL,
        dial_success INTEGER,
        dial_result TEXT,
        report_attempts INTEGER NOT NULL DEFAULT 0,
        last_report_error TEXT,
        created_at TEXT NOT NULL,
        dialing_at TEXT,
        dialed_at TEXT,
        reported_at TEXT,
        is_interactive INTEGER NOT NULL DEFAULT 0,
        attempt_id INTEGER
      )
    ''');
    await db.execute('CREATE INDEX idx_transaction_tasks_state ON transaction_tasks(state)');

    await db.execute('''
      CREATE TABLE sms_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER NOT NULL UNIQUE,
        phone_number TEXT,
        message TEXT,
        purpose TEXT,
        state TEXT NOT NULL,
        send_success INTEGER,
        send_result TEXT,
        report_attempts INTEGER NOT NULL DEFAULT 0,
        last_report_error TEXT,
        created_at TEXT NOT NULL,
        sending_at TEXT,
        sent_at TEXT,
        reported_at TEXT
      )
    ''');
    await db.execute('CREATE INDEX idx_sms_tasks_state ON sms_tasks(state)');

    await _createInteractiveSessionTable(db);
  }

  /// Phase D2: `singleton INTEGER PRIMARY KEY CHECK (singleton = 1)` is a
  /// real database-enforced "at most one row, ever" - not an application-
  /// level check-then-insert, which two separate FlutterEngine connections
  /// (UI + headless, see this class's own doc on why WAL/busy_timeout exist)
  /// opening the same file could otherwise race. An INSERT while a row
  /// already exists fails with a genuine constraint violation.
  Future<void> _createInteractiveSessionTable(Database db) async {
    await db.execute('''
      CREATE TABLE interactive_session (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        transaction_reference TEXT NOT NULL,
        attempt_id INTEGER NOT NULL,
        pending_event TEXT NOT NULL,
        pending_idempotency_key TEXT NOT NULL,
        pending_payload TEXT NOT NULL,
        last_response TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    ''');
  }

  /// Phase D audit (Critique): v1 -> v2 adds `operator` to `transaction_tasks`
  /// so the operator cross-check (`SimResolver.matchesExpectedOperator` on
  /// the native side) has the expected value to compare against for tasks
  /// already sitting in a real device's local queue when this update is
  /// installed - a plain ALTER TABLE, no data loss, no re-fetch needed
  /// (in-flight tasks just have `operator=NULL` until their next
  /// enqueue/refresh, which skips the check exactly like an older backend
  /// that never sent one).
  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 2) {
      await db.execute('ALTER TABLE transaction_tasks ADD COLUMN operator TEXT');
    }
    if (oldVersion < 3) {
      await _createInteractiveSessionTable(db);
    }
    // Phase D4.3: distinguishes a task the interactive session runner must
    // own from a plain task _drainDial() keeps dialing - additive, no data
    // loss; in-flight rows just default to is_interactive=0/attempt_id=NULL
    // until their next enqueue, which behaves exactly like today for them.
    if (oldVersion < 4) {
      await db.execute('ALTER TABLE transaction_tasks ADD COLUMN is_interactive INTEGER NOT NULL DEFAULT 0');
      await db.execute('ALTER TABLE transaction_tasks ADD COLUMN attempt_id INTEGER');
    }
  }

  /// Upserts each server-reported pending task by [PendingTransaction.serverReference]
  /// (the natural key). A task still in flight locally (anything but `done`)
  /// is left completely untouched - it's already being worked. A task that
  /// previously reached `done` is re-armed back to `pending_dial` with the
  /// fresh `ussd_code`/`sim_slot`: `TransactionResultView` can legitimately
  /// hand the same reference back after RetryManager schedules a retry on a
  /// different SIM, and that new attempt must actually get dialed.
  Future<void> enqueueTransactionTasks(List<PendingTransaction> tasks) async {
    final db = await _database;
    await db.transaction((txn) async {
      // Stabilisation RC1 (priorité faible n°12): one batched lookup instead
      // of one SELECT per task - the backend caps a single poll at 10 tasks
      // (see PendingTransactionsView), so this halves the round-trips on a
      // full page rather than doing SELECT+INSERT/UPDATE per task in turn.
      final references = tasks.map((t) => t.serverReference).where((r) => r.isNotEmpty).toSet().toList();
      final existingRows = references.isEmpty
          ? const <Map<String, Object?>>[]
          : await txn.query(
              'transaction_tasks',
              where: 'reference IN (${List.filled(references.length, '?').join(', ')})',
              whereArgs: references,
            );
      final existingByReference = {for (final row in existingRows) row['reference'] as String: row};

      for (final task in tasks) {
        if (task.serverReference.isEmpty) continue;
        final existingRow = existingByReference[task.serverReference];
        final now = DateTime.now().toIso8601String();
        if (existingRow == null) {
          await txn.insert('transaction_tasks', {
            'reference': task.serverReference,
            'transaction_type': task.type,
            'recipient_phone': task.recipientPhone,
            'amount': task.amount,
            'ussd_code': task.ussdCode ?? '',
            'sim_slot': task.simSlot,
            'operator': task.operator,
            'state': TaskState.pendingDial,
            'report_attempts': 0,
            'created_at': now,
            'is_interactive': task.isInteractive ? 1 : 0,
            'attempt_id': task.attemptId,
          });
          continue;
        }
        if (existingRow['state'] == TaskState.done) {
          await txn.update(
            'transaction_tasks',
            {
              'ussd_code': task.ussdCode ?? '',
              'sim_slot': task.simSlot,
              'operator': task.operator,
              'state': TaskState.pendingDial,
              'dial_success': null,
              'dial_result': null,
              'report_attempts': 0,
              'last_report_error': null,
              'created_at': now,
              'dialing_at': null,
              'dialed_at': null,
              'reported_at': null,
              'is_interactive': task.isInteractive ? 1 : 0,
              'attempt_id': task.attemptId,
            },
            where: 'id = ?',
            whereArgs: [existingRow['id']],
          );
        }
        // Any other state: already in flight, leave untouched.
      }
    });
  }

  /// Phase D4.3: excludes interactive rows - those are only ever picked up
  /// by [nextInteractiveTaskToStart], never dialed via the simple
  /// dialUssd()/_drainDial() path.
  Future<TransactionTask?> nextTaskToDial() async {
    final db = await _database;
    final rows = await db.query(
      'transaction_tasks',
      where: 'state = ? AND is_interactive = 0',
      whereArgs: [TaskState.pendingDial],
      orderBy: 'created_at ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : TransactionTask.fromRow(rows.first);
  }

  /// Phase D4.3: the interactive counterpart of [nextTaskToDial] - a task
  /// the interactive session runner must own instead. Never claimed twice
  /// for the same reference: PendingTransactionsView's existing
  /// assigned->dispatched claim (Phase 7) already guarantees the backend
  /// never hands this same reference out again once dispatched, so it can
  /// only ever appear here once.
  Future<TransactionTask?> nextInteractiveTaskToStart() async {
    final db = await _database;
    final rows = await db.query(
      'transaction_tasks',
      where: 'state = ? AND is_interactive = 1',
      whereArgs: [TaskState.pendingDial],
      orderBy: 'created_at ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : TransactionTask.fromRow(rows.first);
  }

  /// Marks a row as handed off to the interactive session runner - from
  /// this point its lifecycle is tracked by `interactive_session`
  /// (started/closed by the runner itself), not by this table anymore.
  /// Returns false if a concurrent drain already claimed it.
  Future<bool> markInteractiveHandedOff(int id) async {
    final db = await _database;
    final updated = await db.update(
      'transaction_tasks',
      {'state': TaskState.done, 'reported_at': DateTime.now().toIso8601String()},
      where: 'id = ? AND state = ?',
      whereArgs: [id, TaskState.pendingDial],
    );
    return updated > 0;
  }

  /// Commits the `dialing` transition **before** the caller makes the actual
  /// platform-channel dial call - this ordering is what makes
  /// [recoverInterruptedDials] able to tell "was mid-dial when we died" apart
  /// from "never started". Returns false (caller must not dial) if the row
  /// moved on already, e.g. a concurrent drain got there first.
  Future<bool> markDialing(int id) async {
    final db = await _database;
    final updated = await db.update(
      'transaction_tasks',
      {'state': TaskState.dialing, 'dialing_at': DateTime.now().toIso8601String()},
      where: 'id = ? AND state = ?',
      whereArgs: [id, TaskState.pendingDial],
    );
    return updated > 0;
  }

  Future<void> markDialed(int id, {required bool? success, required String result}) async {
    final db = await _database;
    await db.update(
      'transaction_tasks',
      {
        'state': TaskState.dialed,
        'dial_success': success == null ? null : (success ? 1 : 0),
        'dial_result': result,
        'dialed_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  /// Rows whose outcome is known but not yet acknowledged by the backend -
  /// the only bucket the report-retry loop is allowed to touch.
  Future<List<TransactionTask>> tasksAwaitingReport() async {
    final db = await _database;
    final rows = await db.query(
      'transaction_tasks',
      where: 'state IN (?, ?)',
      whereArgs: [TaskState.dialed, TaskState.reporting],
      orderBy: 'dialed_at ASC',
    );
    return rows.map(TransactionTask.fromRow).toList();
  }

  Future<void> markReported(int id) async {
    final db = await _database;
    await db.update(
      'transaction_tasks',
      {'state': TaskState.done, 'reported_at': DateTime.now().toIso8601String()},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  /// Reporting failed (e.g. offline) - stays in the awaiting-report bucket
  /// for the next drain tick. Never touches the dial outcome.
  Future<void> recordReportFailure(int id, String error) async {
    final db = await _database;
    await db.rawUpdate(
      'UPDATE transaction_tasks SET state = ?, report_attempts = report_attempts + 1, last_report_error = ? WHERE id = ?',
      [TaskState.reporting, error, id],
    );
  }

  /// Sweeps rows left in `dialing` from a process that died mid-call (crash,
  /// service killed, watchdog restart). They are moved straight to `dialed`
  /// with an indeterminate outcome and **never re-dialed** - see the class
  /// doc. [grace] should stay comfortably under the server's
  /// TRANSACTION_ENGINE.TIMEOUT_SECONDS (90s) so this never races a dial that
  /// is still genuinely in progress.
  Future<int> recoverInterruptedDials({Duration grace = const Duration(seconds: 60)}) async {
    final db = await _database;
    final cutoff = DateTime.now().subtract(grace).toIso8601String();
    return db.update(
      'transaction_tasks',
      {
        'state': TaskState.dialed,
        'dial_success': null,
        'dial_result': 'UNKNOWN_INTERRUPTED',
        'dialed_at': DateTime.now().toIso8601String(),
      },
      where: 'state = ? AND dialing_at <= ?',
      whereArgs: [TaskState.dialing, cutoff],
    );
  }

  /// Count of every task (USSD or SMS) not yet fully settled - feeds the
  /// heartbeat's `current_task_count`/`is_busy` telemetry fields. Phase D4:
  /// an active interactive_session row also counts - it has no row left in
  /// transaction_tasks (see markInteractiveHandedOff) once the runner takes
  /// over, so without this an interactive session in progress would
  /// wrongly report is_busy=false to the backend.
  Future<int> pendingTaskCount() async {
    final db = await _database;
    final txCount = Sqflite.firstIntValue(
      await db.rawQuery(
        "SELECT COUNT(*) AS c FROM transaction_tasks WHERE state != ?",
        [TaskState.done],
      ),
    );
    final smsCount = Sqflite.firstIntValue(
      await db.rawQuery(
        "SELECT COUNT(*) AS c FROM sms_tasks WHERE state != ?",
        [SmsTaskState.done],
      ),
    );
    final interactiveCount = Sqflite.firstIntValue(
      await db.rawQuery('SELECT COUNT(*) AS c FROM interactive_session'),
    );
    return (txCount ?? 0) + (smsCount ?? 0) + (interactiveCount ?? 0);
  }

  // --- SMS tasks: same "at most once" discipline as transaction_tasks,
  // adapted for an outcome that arrives asynchronously (see SmsTaskState's
  // doc) rather than as a direct dial callback. ---

  /// Upserts by [SmsPendingTask.id] (the backend's `SmsTask.id` - the
  /// natural key, unlike transactions there is no reference string). A row
  /// still in flight is left untouched; a `done` row is re-armed, though in
  /// practice the backend does not currently re-issue a completed SMS job
  /// under the same id - this mirrors enqueueTransactionTasks for symmetry
  /// and future-proofing, not a known live scenario today.
  Future<void> enqueueSmsTasks(List<SmsPendingTask> tasks) async {
    final db = await _database;
    await db.transaction((txn) async {
      // Stabilisation RC1 (priorité faible n°12): same batched-lookup
      // optimization as enqueueTransactionTasks, keyed by server_id here.
      final serverIds = tasks.map((t) => t.id).toSet().toList();
      final existingRows = serverIds.isEmpty
          ? const <Map<String, Object?>>[]
          : await txn.query(
              'sms_tasks',
              where: 'server_id IN (${List.filled(serverIds.length, '?').join(', ')})',
              whereArgs: serverIds,
            );
      final existingByServerId = {for (final row in existingRows) row['server_id'] as int: row};

      for (final task in tasks) {
        final existingRow = existingByServerId[task.id];
        final now = DateTime.now().toIso8601String();
        if (existingRow == null) {
          await txn.insert('sms_tasks', {
            'server_id': task.id,
            'phone_number': task.phoneNumber,
            'message': task.message,
            'purpose': task.purpose,
            'state': SmsTaskState.pendingSend,
            'report_attempts': 0,
            'created_at': now,
          });
          continue;
        }
        if (existingRow['state'] == SmsTaskState.done) {
          await txn.update(
            'sms_tasks',
            {
              'phone_number': task.phoneNumber,
              'message': task.message,
              'purpose': task.purpose,
              'state': SmsTaskState.pendingSend,
              'send_success': null,
              'send_result': null,
              'report_attempts': 0,
              'last_report_error': null,
              'created_at': now,
              'sending_at': null,
              'sent_at': null,
              'reported_at': null,
            },
            where: 'id = ?',
            whereArgs: [existingRow['id']],
          );
        }
      }
    });
  }

  Future<SmsQueueTask?> nextSmsToSend() async {
    final db = await _database;
    final rows = await db.query(
      'sms_tasks',
      where: 'state = ?',
      whereArgs: [SmsTaskState.pendingSend],
      orderBy: 'created_at ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : SmsQueueTask.fromRow(rows.first);
  }

  /// Commits the `sending` transition before the native `sendSms` call is
  /// made - same ordering rule as [markDialing], for the same reason.
  Future<bool> markSmsSending(int id) async {
    final db = await _database;
    final updated = await db.update(
      'sms_tasks',
      {'state': SmsTaskState.sending, 'sending_at': DateTime.now().toIso8601String()},
      where: 'id = ? AND state = ?',
      whereArgs: [id, SmsTaskState.pendingSend],
    );
    return updated > 0;
  }

  /// Called once the native sent/delivered outbox reveals an outcome for a
  /// row still in `sending` (see [reconcileSmsOutcomes]) - never called
  /// directly from the dial step, since `sendSms` itself only confirms the
  /// OS accepted the request, not the actual delivery outcome.
  Future<void> markSmsResultKnown(int id, {required bool? success, required String result}) async {
    final db = await _database;
    await db.update(
      'sms_tasks',
      {
        'state': SmsTaskState.sentResultKnown,
        'send_success': success == null ? null : (success ? 1 : 0),
        'send_result': result,
        'sent_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  /// Reconciles a drain of the native sent/delivered outbox (a list of
  /// `{taskId, sent, delivered}` maps, `taskId` being this table's local
  /// `id`) into [markSmsResultKnown] calls - only for rows still `sending`,
  /// so a stray/duplicate outbox entry can never resurrect an already-
  /// reported task.
  Future<void> reconcileSmsOutcomes(List<Map<dynamic, dynamic>> outcomes) async {
    for (final entry in outcomes) {
      final id = entry['taskId'] as int?;
      final sent = entry['sent'] as String?;
      if (id == null || sent == null) continue;
      final db = await _database;
      final rows = await db.query('sms_tasks', where: 'id = ? AND state = ?', whereArgs: [id, SmsTaskState.sending]);
      if (rows.isEmpty) {
        // Stabilisation RC1 (priorité moyenne n°11): most commonly this
        // means [recoverInterruptedSmsSends] already moved the row past
        // `sending` (UNKNOWN_INTERRUPTED) before this native receipt finally
        // arrived - correct to never resurrect it (see the class doc), but
        // silently dropping it left no trace this ever happened. A trace
        // costs nothing and helps tell "receipts are just slow on this
        // network/OEM" apart from "outcomes are being lost".
        developer.log(
          'Accusé SMS tardif ignoré (déjà hors de sending) : id=$id sent=$sent delivered=${entry['delivered']}',
          name: 'LocalQueueRepository',
        );
        continue;
      }
      final delivered = entry['delivered'] as String?;
      final success = sent == 'sent';
      final result = delivered != null ? '$sent/$delivered' : sent;
      await markSmsResultKnown(id, success: success, result: result);
    }
  }

  Future<List<SmsQueueTask>> smsTasksAwaitingReport() async {
    final db = await _database;
    final rows = await db.query(
      'sms_tasks',
      where: 'state IN (?, ?)',
      whereArgs: [SmsTaskState.sentResultKnown, SmsTaskState.reporting],
      orderBy: 'sent_at ASC',
    );
    return rows.map(SmsQueueTask.fromRow).toList();
  }

  Future<void> markSmsReported(int id) async {
    final db = await _database;
    await db.update(
      'sms_tasks',
      {'state': SmsTaskState.done, 'reported_at': DateTime.now().toIso8601String()},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> recordSmsReportFailure(int id, String error) async {
    final db = await _database;
    await db.rawUpdate(
      'UPDATE sms_tasks SET state = ?, report_attempts = report_attempts + 1, last_report_error = ? WHERE id = ?',
      [SmsTaskState.reporting, error, id],
    );
  }

  /// Same purpose as [recoverInterruptedDials], longer grace window: an SMS
  /// sent/delivered receipt can legitimately take longer than a USSD
  /// response, and some OEMs delay or drop broadcast receivers under
  /// aggressive battery management.
  Future<int> recoverInterruptedSmsSends({Duration grace = const Duration(minutes: 2)}) async {
    final db = await _database;
    final cutoff = DateTime.now().subtract(grace).toIso8601String();
    return db.update(
      'sms_tasks',
      {
        'state': SmsTaskState.sentResultKnown,
        'send_success': null,
        'send_result': 'UNKNOWN_INTERRUPTED',
        'sent_at': DateTime.now().toIso8601String(),
      },
      where: 'state = ? AND sending_at <= ?',
      whereArgs: [SmsTaskState.sending, cutoff],
    );
  }

  // --- Interactive USSD session (Phase D2) - a single row, see
  // InteractiveSession's doc and _createInteractiveSessionTable's for why
  // the schema itself (not just this class) enforces "at most one". ---

  /// Returns true if the session was created, false if one was already
  /// active (a real PRIMARY KEY/CHECK violation was caught here - not an
  /// application-level "if exists" guess, see the table's own doc on why
  /// that distinction matters with two FlutterEngine connections).
  Future<bool> startInteractiveSession({
    required String transactionReference,
    required int attemptId,
  }) async {
    final db = await _database;
    final now = DateTime.now().toIso8601String();
    try {
      await db.insert('interactive_session', {
        'singleton': 1,
        'transaction_reference': transactionReference,
        'attempt_id': attemptId,
        'pending_event': '',
        'pending_idempotency_key': '',
        'pending_payload': '',
        'created_at': now,
        'updated_at': now,
      });
      return true;
    } on DatabaseException catch (e) {
      if (e.isUniqueConstraintError() || e.isNotNullConstraintError() || e.toString().contains('CHECK')) {
        return false;
      }
      rethrow;
    }
  }

  Future<InteractiveSession?> currentInteractiveSession() async {
    final db = await _database;
    final rows = await db.query('interactive_session', where: 'singleton = 1', limit: 1);
    return rows.isEmpty ? null : InteractiveSession.fromRow(rows.first);
  }

  /// Step 3 of the mandatory ordering (Phase D2, point 9): committed BEFORE
  /// the HTTP call is ever made, so a network failure mid-request always
  /// leaves the SAME event/key/payload behind for a retry to re-read -
  /// never regenerated here or by any caller of this method.
  Future<void> recordPendingStepEvent({
    required String event,
    required String idempotencyKey,
    required String payload,
  }) async {
    final db = await _database;
    await db.update(
      'interactive_session',
      {
        'pending_event': event,
        'pending_idempotency_key': idempotencyKey,
        'pending_payload': payload,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'singleton = 1',
    );
  }

  /// Step 5: only called after a successful HTTP response - a network
  /// failure never reaches this, leaving recordPendingStepEvent's values as
  /// the ones a retry will resend.
  Future<void> recordStepResponse(String response) async {
    final db = await _database;
    await db.update(
      'interactive_session',
      {'last_response': response, 'updated_at': DateTime.now().toIso8601String()},
      where: 'singleton = 1',
    );
  }

  /// One generic cleanup regardless of why the session ended (SUCCESS/
  /// FAILED/TIMEOUT/CANCELLED) - the backend's TransactionAttempt/
  /// TransactionEvent already keep that permanent history, so this table
  /// has no reason to distinguish the cause, only whether a session is
  /// currently occupying the Gateway.
  Future<void> closeInteractiveSession() async {
    final db = await _database;
    await db.delete('interactive_session', where: 'singleton = 1');
  }

  Future<void> close() async {
    final db = _db;
    if (db != null) {
      await db.close();
      _db = null;
    }
  }
}
