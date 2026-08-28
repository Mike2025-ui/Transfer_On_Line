import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transfer_on_line/services/auth_service.dart';

class _InMemoryStore implements AuthTokenStore {
  final Map<String, String> _values = {};

  @override
  Future<String?> read(String key) async => _values[key];

  @override
  Future<void> write(String key, String value) async => _values[key] = value;

  @override
  Future<void> delete(String key) async => _values.remove(key);
}

String _fakeJwt({required int exp}) {
  String segment(Map<String, dynamic> data) =>
      base64Url.encode(utf8.encode(jsonEncode(data))).replaceAll('=', '');
  return '${segment({
        'alg': 'none'
      })}.${segment({
        'exp': exp
      })}.sig';
}

void main() {
  final farFuture = DateTime.now().toUtc().add(const Duration(days: 1)).millisecondsSinceEpoch ~/ 1000;
  final longPast = DateTime.now().toUtc().subtract(const Duration(days: 1)).millisecondsSinceEpoch ~/ 1000;

  group('AuthService.restoreSession', () {
    test('no stored session returns null and makes no network call', () async {
      var calls = 0;
      final auth = AuthService(
        store: _InMemoryStore(),
        client: MockClient((request) async {
          calls++;
          return http.Response('{}', 200);
        }),
      );

      final session = await auth.restoreSession();

      expect(session, isNull);
      expect(calls, 0, reason: 'an empty store must not trigger a refresh call');
    });

    test('a still-valid access token is restored without calling the backend', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000001');
      await store.write('auth_access_token', _fakeJwt(exp: farFuture));
      await store.write('auth_refresh_token', 'refresh-token-value');
      var calls = 0;
      final auth = AuthService(
        store: store,
        client: MockClient((request) async {
          calls++;
          return http.Response('{}', 200);
        }),
      );

      final session = await auth.restoreSession();

      expect(session, isNotNull);
      expect(session!.phoneNumber, '+2250700000001');
      expect(calls, 0, reason: 'the device is already known - no OTP, no refresh call needed');
    });

    test('an expired access token is silently refreshed - device stays known', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000002');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'old-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async {
          expect(request.url.path, contains('/auth/token/refresh/'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['refresh'], 'old-refresh-token');
          return http.Response(
            jsonEncode({'access': _fakeJwt(exp: farFuture), 'refresh': 'rotated-refresh-token'}),
            200,
          );
        }),
      );

      final session = await auth.restoreSession();

      expect(session, isNotNull);
      expect(session!.phoneNumber, '+2250700000002');
      // the rotated refresh token must be persisted, not silently dropped
      expect(await store.read('auth_refresh_token'), 'rotated-refresh-token');
    });

    test('a refresh token the backend rejects with 401 clears the stored session - OTP required again', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000003');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'expired-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => http.Response('{"detail":"token invalid"}', 401)),
      );

      final session = await auth.restoreSession();

      expect(session, isNull);
      expect(await store.read('auth_phone_number'), isNull);
      expect(await store.read('auth_access_token'), isNull);
      expect(await store.read('auth_refresh_token'), isNull);
    });

    test('a refresh token the backend rejects with 403 also clears the stored session', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000006');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'forbidden-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => http.Response('{"detail":"forbidden"}', 403)),
      );

      final session = await auth.restoreSession();

      expect(session, isNull);
      expect(await store.read('auth_refresh_token'), isNull);
    });

    test('P0-1: a network timeout during refresh keeps the session - never treated as an invalid token', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000007');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'still-valid-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => throw TimeoutException('timed out')),
      );

      final session = await auth.restoreSession();

      expect(session, isNotNull, reason: 'a transient network failure must not force a re-login');
      expect(session!.phoneNumber, '+2250700000007');
      expect(await store.read('auth_refresh_token'), 'still-valid-refresh-token',
          reason: 'tokens must not be deleted just because the network failed');
    });

    test('P0-1: being offline (SocketException) during refresh keeps the session', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000008');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'still-valid-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => throw const SocketException('no network')),
      );

      final session = await auth.restoreSession();

      expect(session, isNotNull);
      expect(await store.read('auth_access_token'), isNotNull);
      expect(await store.read('auth_refresh_token'), isNotNull);
    });

    test('P0-1: an unreachable/erroring server (500) during refresh keeps the session', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000009');
      await store.write('auth_access_token', _fakeJwt(exp: longPast));
      await store.write('auth_refresh_token', 'still-valid-refresh-token');
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => http.Response('Internal Server Error', 500)),
      );

      final session = await auth.restoreSession();

      expect(session, isNotNull, reason: 'a 500 is a server problem, not proof the token is invalid');
      expect(await store.read('auth_refresh_token'), isNotNull);
    });
  });

  group('AuthService.logout', () {
    test('explicitly removes the stored session', () async {
      final store = _InMemoryStore();
      await store.write('auth_phone_number', '+2250700000010');
      await store.write('auth_access_token', 'some-access-token');
      await store.write('auth_refresh_token', 'some-refresh-token');
      final auth = AuthService(store: store, client: MockClient((request) async => http.Response('{}', 200)));

      await auth.logout();

      expect(await store.read('auth_phone_number'), isNull);
      expect(await store.read('auth_access_token'), isNull);
      expect(await store.read('auth_refresh_token'), isNull);
    });
  });

  group('AuthService.requestOtp', () {
    test('returns the verification_id Aion assigned via the backend - never a code', () async {
      final auth = AuthService(
        store: _InMemoryStore(),
        client: MockClient((request) async {
          expect(request.url.path, contains('/auth/otp/request/'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['phone_number'], '+2250700000040');
          return http.Response(jsonEncode({'status': 'sent', 'verification_id': 42}), 200);
        }),
      );

      final response = await auth.requestOtp('+2250700000040');

      expect(response['verification_id'], 42);
      expect(response.containsKey('debug_code'), isFalse, reason: 'Aion is the sole OTP provider - no code ever reaches the client');
    });

    test('a backend error raises with its message', () async {
      final auth = AuthService(
        store: _InMemoryStore(),
        client: MockClient((request) async => http.Response(jsonEncode({'error': 'Unable to send verification code'}), 400)),
      );

      expect(
        () => auth.requestOtp('+2250700000041'),
        throwsA(predicate((e) => e.toString().contains('Unable to send verification code'))),
      );
    });
  });

  group('AuthService.verifyOtp', () {
    test('forwards the verification_id unchanged and stores the phone number and both tokens on success', () async {
      final store = _InMemoryStore();
      final auth = AuthService(
        store: store,
        client: MockClient((request) async {
          expect(request.url.path, contains('/auth/otp/verify/'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['verification_id'], 42);
          expect(body['code'], '123456');
          return http.Response(
            jsonEncode({
              'access': _fakeJwt(exp: farFuture),
              'refresh': 'fresh-refresh-token',
              'phone_number': '+2250700000004',
            }),
            200,
          );
        }),
      );

      final session = await auth.verifyOtp('+2250700000004', '123456', 42);

      expect(session.phoneNumber, '+2250700000004');
      expect(await store.read('auth_refresh_token'), 'fresh-refresh-token');
    });

    test('a rejected code raises with the backend error message, stores nothing', () async {
      final store = _InMemoryStore();
      final auth = AuthService(
        store: store,
        client: MockClient((request) async => http.Response(jsonEncode({'error': 'Code invalide ou expiré'}), 400)),
      );

      expect(
        () => auth.verifyOtp('+2250700000005', '000000', 42),
        throwsA(predicate((e) => e.toString().contains('Code invalide ou expiré'))),
      );
      await Future<void>.delayed(Duration.zero);
      expect(await store.read('auth_access_token'), isNull);
    });
  });
}
