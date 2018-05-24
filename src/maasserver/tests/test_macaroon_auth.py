# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import (
    datetime,
    timedelta,
)
import json
from unittest import (
    mock,
    TestCase,
)

from django.contrib.auth.models import User
from django.http import HttpResponse
import maasserver.macaroon_auth
from maasserver.macaroon_auth import (
    _get_authentication_caveat,
    _get_macaroon_oven_key,
    _IDClient,
    APIError,
    IDMClient,
    IDM_USER_CHECK_INTERVAL,
    KeyStore,
    MacaroonAPIAuthentication,
    MacaroonAuthorizationBackend,
    validate_user_external_auth,
)
from maasserver.middleware import ExternalAuthInfoMiddleware
from maasserver.models import (
    Config,
    RootKey,
)
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from maasserver.worker_user import get_worker_user
from macaroonbakery.bakery import (
    IdentityError,
    SimpleIdentity,
    VerificationError,
)
from metadataserver.nodeinituser import get_node_init_user
import requests


class TestIDClient(MAASServerTestCase):

    def setUp(self):
        super().setUp()
        self.client = _IDClient('https://example.com')

    def test_declared_entity(self):
        identity = self.client.declared_identity(None, {'username': 'user'})
        self.assertEqual(identity.id(), 'user')

    def test_declared_entity_no_username(self):
        self.assertRaises(
            IdentityError, self.client.declared_identity, None,
            {'other': 'stuff'})

    def test_identity_from_context(self):
        _, [caveat] = self.client.identity_from_context(None)
        self.assertEqual(caveat.location, 'https://example.com')
        self.assertEqual(caveat.condition, 'is-authenticated-user')

    def test_identity_from_context_with_domain(self):
        client = _IDClient('https://example.com', auth_domain='mydomain')
        _, [caveat] = client.identity_from_context(None)
        self.assertEqual(caveat.location, 'https://example.com')
        self.assertEqual(caveat.condition, 'is-authenticated-user @mydomain')


class TestIDMClient(MAASServerTestCase):

    def setUp(self):
        super().setUp()
        Config.objects.set_config(
            'external_auth_url', 'https://auth.example.com')
        Config.objects.set_config('external_auth_user', 'user@idm')
        Config.objects.set_config(
            'external_auth_key',
            'x0NeASLPFhOFfq3Q9M0joMveI4HjGwEuJ9dtX/HTSRY=')

    @mock.patch('requests.request')
    def test_get_groups(self, mock_request):
        groups = ['group1', 'group2']
        response = mock.MagicMock(status_code=200)
        response.json.return_value = groups
        mock_request.return_value = response
        client = IDMClient()
        self.assertEqual(client.get_groups('foo'), groups)
        mock_request.assert_called_with(
            'GET', 'https://auth.example.com/v1/u/foo/groups',
            auth=mock.ANY, cookies=mock.ANY)

    @mock.patch('requests.request')
    def test_get_groups_user_not_found(self, mock_request):
        response = mock.MagicMock(status_code=404)
        response.json.return_value = {
            'code': 'not found',
            'messsage': 'user foo not found'}
        mock_request.return_value = response
        client = IDMClient()
        self.assertRaises(APIError, client.get_groups, 'foo')


class TestValidateUserExternalAuth(MAASServerTestCase):

    def setUp(self):
        super().setUp()
        self.client = mock.Mock()
        self.user = factory.make_User()
        self.now = datetime.utcnow()
        # by default, the user has to be checked again
        self.default_last_check = (
            self.now - IDM_USER_CHECK_INTERVAL - timedelta(minutes=10))
        self.user.userprofile.auth_last_check = self.default_last_check
        self.user.userprofile.save()

    def test_interval_not_expired(self):
        last_check = self.now - timedelta(minutes=10)
        self.user.userprofile.auth_last_check = last_check
        self.user.userprofile.save()
        valid = validate_user_external_auth(
            self.user, now=lambda: self.now, client=self.client)
        self.assertTrue(valid)
        # user is not checked again, last check time is not updated
        self.client.get_groups.assert_not_called()
        self.assertEqual(self.user.userprofile.auth_last_check, last_check)

    def test_valid_user_check(self):
        # user exists, so group info is returned
        self.client.get_groups.return_value = ['group1', 'group2']
        valid = validate_user_external_auth(
            self.user, now=lambda: self.now, client=self.client)
        self.assertTrue(valid)
        # user is checked again, last check time is updated
        self.client.get_groups.assert_called()
        self.assertEqual(self.user.userprofile.auth_last_check, self.now)
        # user is still enabled
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.is_superuser)

    def test_system_user_valid_no_check(self):
        client = mock.MagicMock()
        self.assertTrue(
            validate_user_external_auth(get_worker_user(), client=client))
        self.assertTrue(
            validate_user_external_auth(get_node_init_user(), client=client))
        client.get_groups.assert_not_called()

    def test_valid_inactive_user_is_active(self):
        self.user.is_active = False
        self.client.get_groups.return_value = ['group1', 'group2']
        valid = validate_user_external_auth(
            self.user, now=lambda: self.now, client=self.client)
        self.assertTrue(valid)
        self.assertTrue(self.user.is_active)

    def test_invalid_user_check(self):
        self.client.get_groups.side_effect = APIError(404, 'user not found')
        valid = validate_user_external_auth(
            self.user, now=lambda: self.now, client=self.client)
        self.assertFalse(valid)
        # user is checked again, last check time is updated
        self.client.get_groups.assert_called()
        self.assertEqual(self.user.userprofile.auth_last_check, self.now)
        # user is disabled
        self.assertFalse(self.user.is_active)

    def test_user_in_admin_group(self):
        self.client.get_groups.return_value = ['group1', 'group2']
        valid = validate_user_external_auth(
            self.user, admin_group='group2', now=lambda: self.now,
            client=self.client)
        self.assertTrue(valid)
        self.assertTrue(self.user.is_superuser)

    def test_user_not_in_admin_group(self):
        self.client.get_groups.return_value = ['group1', 'group2']
        valid = validate_user_external_auth(
            self.user, admin_group='admins', now=lambda: self.now,
            client=self.client)
        self.assertTrue(valid)
        self.assertFalse(self.user.is_superuser)


class MacaroonBakeryMockMixin:
    """Mixin providing mock helpers for tests involving macaroonbakery."""

    def mock_service_key_request(self):
        """Mock request to get the key from the external service.

        Bakery internally performs this request.
        """
        mock_result = mock.Mock()
        mock_result.status_code = 200
        mock_result.json.return_value = {
            "PublicKey": "CIdWcEUN+0OZnKW9KwruRQnQDY/qqzVdD30CijwiWCk=",
            "Version": 3}
        mock_get = self.patch(requests, 'get')
        mock_get.return_value = mock_result

    def mock_auth_info(self, username=None, exception=None):
        """Mock bakery authentication, returning an identity.

        If a username is specified, a SimpleIdentity is returned.
        If an exception is specified, it's raised by the checker allow()
        method.

        Return the mocked bakery object.

        """
        mock_auth_checker = mock.Mock()
        if username:
            mock_auth_checker.allow.return_value = mock.Mock(
                identity=SimpleIdentity(user=username))
        if exception:
            mock_auth_checker.allow.side_effect = exception

        mock_bakery = mock.Mock()
        mock_bakery.checker.auth.return_value = mock_auth_checker
        mock_get_bakery = self.patch(maasserver.macaroon_auth, '_get_bakery')
        mock_get_bakery.return_value = mock_bakery
        return mock_bakery


class TestMacaroonAPIAuthentication(MAASServerTestCase,
                                    MacaroonBakeryMockMixin):

    def setUp(self):
        super().setUp()
        Config.objects.set_config(
            'external_auth_url', 'https://auth.example.com')
        Config.objects.set_config('external_auth_admin_group', 'admins')
        self.auth = MacaroonAPIAuthentication()
        self.mock_service_key_request()
        self.mock_validate = self.patch(
            maasserver.macaroon_auth, 'validate_user_external_auth')
        self.mock_validate.return_value = True

    def get_request(self):
        request = factory.make_fake_request('/')
        # add external_auth_info to the request
        return ExternalAuthInfoMiddleware(lambda request: request)(request)

    def test_is_authenticated_no_external_auth(self):
        # authentication details are provided
        self.mock_auth_info(username=factory.make_string())
        # ... but external auth is disabled
        Config.objects.set_config('external_auth_url', '')
        self.assertFalse(self.auth.is_authenticated(self.get_request()))

    def test_is_authenticated_no_auth_details(self):
        self.assertFalse(self.auth.is_authenticated(self.get_request()))

    def test_is_authenticated_with_auth(self):
        user = factory.make_User()
        self.mock_auth_info(username=user.username)
        self.assertTrue(self.auth.is_authenticated(self.get_request()))

    def test_is_authenticated_with_auth_creates_user(self):
        username = factory.make_string()
        self.mock_auth_info(username=username)
        self.assertTrue(self.auth.is_authenticated(self.get_request()))
        user = User.objects.get(username=username)
        self.assertIsNotNone(user.id)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.userprofile.is_local)
        self.mock_validate.assert_called_with(user, admin_group='admins')

    def test_is_authenticated_user_exists_but_local(self):
        user = factory.make_User()
        user.userprofile.is_local = True
        user.userprofile.save()
        self.mock_auth_info(username=user.username)
        self.assertFalse(self.auth.is_authenticated(self.get_request()))

    def test_is_authenticated_validate_if_exists(self):
        user = factory.make_User()
        self.mock_auth_info(username=user.username)
        self.assertTrue(self.auth.is_authenticated(self.get_request()))
        self.mock_validate.assert_called()

    def test_is_authenticated_fails_if_not_validated(self):
        self.mock_validate.return_value = False
        user = factory.make_User()
        self.mock_auth_info(username=user.username)
        self.assertFalse(self.auth.is_authenticated(self.get_request()))

    def test_challenge_no_external_auth(self):
        Config.objects.set_config('external_auth_url', '')
        response = self.auth.challenge(self.get_request())
        self.assertEqual(response.status_code, 401)

    def test_challenge(self):
        response = self.auth.challenge(self.get_request())
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.content)
        self.assertEqual(payload['Code'], 'macaroon discharge required')
        macaroon = payload['Info']['Macaroon']
        # macaroon is requested for this service
        self.assertEqual(macaroon['location'], 'http://testserver/')
        # a third party caveat is added for the external authentication service
        third_party_urls = [
            caveat['cl'] for caveat in macaroon['caveats'] if 'cl' in caveat]
        self.assertEqual(third_party_urls, ['https://auth.example.com'])


class TestMacaroonAuthorizationBackend(MAASServerTestCase):

    def setUp(self):
        super().setUp()
        Config.objects.set_config(
            'external_auth_url', 'https://auth.example.com')
        Config.objects.set_config('external_auth_admin_group', 'admins')
        self.backend = MacaroonAuthorizationBackend()
        self.mock_validate = self.patch(
            maasserver.macaroon_auth, 'validate_user_external_auth')
        self.mock_validate.return_value = True

    def get_request(self):
        request = factory.make_fake_request('/')
        # add external_auth_info to the request
        return ExternalAuthInfoMiddleware(lambda request: request)(request)

    def test_authenticate(self):
        user = factory.make_User()
        identity = SimpleIdentity(user=user.username)
        self.assertEqual(
            self.backend.authenticate(
                self.get_request(), identity=identity),
            user)

    def test_authenticate_create_user(self):
        username = factory.make_string()
        identity = SimpleIdentity(user=username)
        user = self.backend.authenticate(self.get_request(), identity=identity)
        self.assertIsNotNone(user.id)
        self.assertEqual(user.username, username)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.userprofile.is_local)
        self.mock_validate.assert_called_with(user, admin_group='admins')

    def test_authenticate_deactived_user_activate(self):
        user = factory.make_User()
        user.is_active = False
        user.save()
        identity = SimpleIdentity(user=user.username)
        authenticated_user = self.backend.authenticate(
            self.get_request(), identity=identity)
        self.assertTrue(authenticated_user.is_active)

    def test_authenticate_no_identity(self):
        self.assertIsNone(
            self.backend.authenticate(self.get_request(), identity=None))

    def test_authenticate_external_auth_not_enabled(self):
        Config.objects.set_config('external_auth_url', '')
        username = factory.make_string()
        identity = SimpleIdentity(user=username)
        self.assertIsNone(
            self.backend.authenticate(self.get_request(), identity=identity))

    def test_authenticate_local_user_denied(self):
        user = factory.make_User(is_local=True)
        identity = SimpleIdentity(user=user.username)
        self.assertIsNone(
            self.backend.authenticate(self.get_request(), identity=identity))

    def test_authenticate_validate_fails(self):
        self.mock_validate.return_value = False
        user = factory.make_User()
        identity = SimpleIdentity(user=user.username)
        self.assertIsNone(
            self.backend.authenticate(self.get_request(), identity=identity))
        self.mock_validate.assert_called_with(user, admin_group='admins')


class TestMacaroonOvenKey(MAASServerTestCase):

    def test__get_macaroon_oven_key(self):
        key = _get_macaroon_oven_key()
        self.assertEqual(
            Config.objects.get_config('macaroon_private_key'),
            key.serialize().decode('ascii'))

    def test__get_macaroon_oven_key_existing(self):
        key = _get_macaroon_oven_key()
        self.assertEqual(_get_macaroon_oven_key(), key)


class TestKeyStore(MAASServerTestCase):

    def setUp(self):
        super().setUp()
        self.expiry_duration = timedelta(hours=4)
        self.generate_interval = timedelta(hours=1)
        self.now = datetime.now()
        self.store = KeyStore(
            self.expiry_duration, generate_interval=self.generate_interval,
            now=lambda: self.now)

    def test_intervals(self):
        self.assertEqual(self.store.expiry_duration, self.expiry_duration)
        self.assertEqual(self.store.generate_interval, self.generate_interval)

    def test_generate_interval_default(self):
        interval = timedelta(hours=1)
        store = KeyStore(interval)
        self.assertEqual(store.generate_interval, interval)

    def test_root_key(self):
        material, key_id = self.store.root_key()
        key = RootKey.objects.get(pk=int(key_id))
        self.assertEqual(key.material.tobytes(), material)
        self.assertEqual(
            key.expiration,
            self.now + self.expiry_duration + self.generate_interval)

    def test_root_key_reuse_existing(self):
        material1, key_id1 = self.store.root_key()
        # up to the generate interval, the same key is reused
        self.now += self.generate_interval
        material2, key_id2 = self.store.root_key()
        self.assertEqual(key_id1, key_id2)
        self.assertEqual(material1, material2)

    def test_root_key_new_key_after_interval(self):
        material1, key_id1 = self.store.root_key()
        self.now += self.generate_interval + timedelta(seconds=1)
        material2, key_id2 = self.store.root_key()
        self.assertNotEqual(key_id1, key_id2)
        self.assertNotEqual(material1, material2)

    def test_root_key_expired_ignored(self):
        _, key_id1 = self.store.root_key()
        key = RootKey.objects.first()
        key.expiration = self.now - timedelta(days=1)
        key.save()
        _, key_id2 = self.store.root_key()
        # a new key is created since one is expired
        self.assertNotEqual(key_id2, key_id1)

    def test_root_key_expired_removed(self):
        factory.make_RootKey(expiration=self.now - timedelta(days=1))
        factory.make_RootKey(expiration=self.now - timedelta(days=2))
        _, key_id = self.store.root_key()
        # expired keys have been removed
        self.assertCountEqual(
            [(int(key_id),)], RootKey.objects.values_list('id'))

    def test_get(self):
        material, key_id = self.store.root_key()
        self.assertEqual(self.store.get(key_id), material)

    def test_get_expired(self):
        _, key_id = self.store.root_key()
        key = RootKey.objects.get(pk=int(key_id))
        # expire the key
        key.expiration = self.now - timedelta(days=1)
        key.save()
        self.assertIsNone(self.store.get(key_id))

    def test_get_not_found(self):
        self.assertIsNone(self.store.get(b'-1'))

    def test_get_not_found_id_not_numeric(self):
        self.assertIsNone(self.store.get(b'invalid'))


class TestMacaroonDischargeRequest(MAASServerTestCase,
                                   MacaroonBakeryMockMixin):

    def setUp(self):
        super().setUp()
        Config.objects.set_config(
            'external_auth_url', 'https://auth.example.com')
        Config.objects.set_config('external_auth_admin_group', 'admins')
        self.mock_service_key_request()
        self.mock_validate = self.patch(
            maasserver.macaroon_auth, 'validate_user_external_auth')
        self.mock_validate.return_value = True

    def test_discharge_request(self):
        response = self.client.get('/accounts/discharge-request/')
        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload['Code'], 'macaroon discharge required')
        macaroon = payload['Info']['Macaroon']
        # macaroon is requested for this service
        self.assertEqual(macaroon['location'], 'http://testserver/')
        # a third party caveat is added for the external authentication service
        third_party_urls = [
            caveat['cl'] for caveat in macaroon['caveats'] if 'cl' in caveat]
        self.assertEqual(third_party_urls, ['https://auth.example.com'])

    def test_discharge_request_validation_failed(self):
        mock_bakery = self.mock_auth_info(
            exception=VerificationError('expired!'))
        mock_auth_request = self.patch(
            maasserver.macaroon_auth, '_authorization_request')
        response = HttpResponse()  # to check that the same object is returned
        mock_auth_request.return_value = response
        self.assertIs(
            self.client.get('/accounts/discharge-request/'), response)
        mock_auth_request.assert_called_with(
            mock_bakery, auth_endpoint='https://auth.example.com',
            auth_domain='', req_headers={'cookie': ''})

    def test_discharge_request_strip_url_trailing_slash(self):
        Config.objects.set_config(
            'external_auth_url', 'https://auth.example.com:1234/')
        response = self.client.get('/accounts/discharge-request/')
        macaroon = response.json()['Info']['Macaroon']
        third_party_urls = [
            caveat['cl'] for caveat in macaroon['caveats'] if 'cl' in caveat]
        self.assertEqual(third_party_urls, ['https://auth.example.com:1234'])

    def test_discharge_request_no_external_auth(self):
        Config.objects.set_config('external_auth_url', '')
        response = self.client.get('/accounts/discharge-request/')
        self.assertEqual(response.status_code, 404)

    def test_authenticated_user(self):
        user = factory.make_User()
        self.mock_auth_info(username=user.username)
        response = self.client.get('/accounts/discharge-request/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {'id': user.id, 'username': user.username})

    def test_authenticated_user_created(self):
        username = factory.make_string()
        self.mock_auth_info(username=username)
        response = self.client.get('/accounts/discharge-request/')
        user = User.objects.get(username=username)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {'id': user.id, 'username': user.username})


class TestGetAuthenticationCaveat(TestCase):

    def test_caveat(self):
        caveat = _get_authentication_caveat(
            'https://example.com', domain='mydomain')
        self.assertEqual(caveat.location, 'https://example.com')
        self.assertEqual(caveat.condition, 'is-authenticated-user @mydomain')

    def test_caveat_no_domain(self):
        caveat = _get_authentication_caveat('https://example.com')
        self.assertEqual(caveat.location, 'https://example.com')
        self.assertEqual(caveat.condition, 'is-authenticated-user')

    def test_caveat_empty_domain(self):
        caveat = _get_authentication_caveat(
            'https://example.com', domain='')
        self.assertEqual(caveat.location, 'https://example.com')
        self.assertEqual(caveat.condition, 'is-authenticated-user')
