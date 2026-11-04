import os, time, unittest, tempfile, shutil
from launcher.supervisor import Supervisor

class DummyBus:
    def __init__(self):
        self.state_data = {"status":"running","turn":None,"turn_since":None}
        self.logs=[]
    def state(self):
        return self.state_data.copy()
    def write_state(self, state):
        self.state_data.update(state)
    def append_log(self, seat, kind, msg):
        self.logs.append((seat, kind, msg))
    def commit_all(self, msg):
        pass
    def roster(self):
        return {"seats":{}}
    def open_gate(self, *a, **kw):
        pass

class TestDeadlockFix(unittest.TestCase):
    def setUp(self):
        self.original_tz = os.environ.get('TZ')
        self.bus=DummyBus()
        self.sup=Supervisor(repo='.', stall_timeout=3600)
        self.sup.bus=self.bus
        # inject counter
        self.sup._routing_failures=0
    def tearDown(self):
        if self.original_tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self.original_tz
        time.tzset()
    def test_no_stall_utc(self):
        # set turn_since 5 seconds ago UTC
        ts=time.time()-5
        self.bus.state_data['turn']='coordinator'
        self.bus.state_data['turn_since']=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))
        # set TZ offset +2
        os.environ['TZ']='Europe/Berlin'
        time.tzset()
        self.sup._check_stall(self.bus.state())
        self.assertNotIn('coordinator', self.sup._stalled_seats)
    def test_stall_detected_after_timeout(self):
        # set turn_since 3 hours ago UTC, exceeds stall_timeout of 1 hour
        ts=time.time()-3*60*60
        self.bus.state_data['turn']='coordinator'
        self.bus.state_data['turn_since']=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))
        os.environ['TZ']='Europe/Berlin'
        time.tzset()
        self.sup._check_stall(self.bus.state())
        self.assertIn('coordinator', self.sup._stalled_seats)
    def test_routing_failure_first(self):
        self.bus.state_data['status']='running'
        self.bus.state_data['turn']=None
        self.sup._check_stall(self.bus.state())
        self.assertIn(('supervisor','routing-failure'), [(s,k) for s,k,_ in self.bus.logs])
        self.assertEqual(self.bus.state_data['turn'],'coordinator')
    def test_routing_failure_escalate(self):
        self.bus.state_data['status']='running'
        self.bus.state_data['turn']=None
        # first call
        self.sup._check_stall(self.bus.state())
        # second call should trigger escalation
        self.sup._check_stall(self.bus.state())
        # escalation opens gate -> no direct check, ensure no second routing-failure log
        count=sum(1 for _,k,_ in self.bus.logs if k=='routing-failure')
        self.assertEqual(count,1)
    def test_done_no_action(self):
        self.bus.state_data.update({'status':'done','turn':None})
        self.sup._check_stall(self.bus.state())
        self.assertEqual(len(self.bus.logs),0)

if __name__=='__main__':
    unittest.main()
