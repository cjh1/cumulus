from tests import base

def setUpModule():
    base.enabledPlugins.append('cumulus')
    base.startServer()


def tearDownModule():
    base.stopServer()

class StarclusterconfigTestCase(base.TestCase):
    def setUp(self):
        super(StarclusterconfigTestCase, self).setUp()

        users = ({
            'email': 'cumulus@email.com',
            'login': 'cumulus',
            'firstName': 'First',
            'lastName': 'Last',
            'password': 'goodpassword'
        }, {
            'email': 'regularuser@email.com',
            'login': 'regularuser',
            'firstName': 'First',
            'lastName': 'Last',
            'password': 'goodpassword'
        })
        self._cumulus, self._user = \
            [self.model('user').createUser(**user) for user in users]

        self._group = self.model('group').createGroup('cumulus', self._admin)

        print self._group

    def test_create(self):
        print "here"
        body = {
             'config': {},
             'name': 'test'
        }

        r = self.request('/starcluster-configs', method='POST', body=body, user=self._cumulus)
        self.assertStatusOk(r)
        self.assertEqual(len(r.json), 1)
