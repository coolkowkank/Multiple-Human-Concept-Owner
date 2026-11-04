import os, time, unittest, tempfile, shutil
from launcher.supervisor import Supervisor

class DummyBus:
    def __init__(self):
        self.state_data = {"status":"running","turn":None,"turn_since":None}
        self.logs=[]
        self.opened_gates=[]
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
        self.opened_gates.append((a, kw))

class TestDeadlockFix(unittest.TestCase):
    def setUp(self):
        self.original_tz = os.environ.get('TZ')
        self.bus=DummyBus()
        self.sup=Supervisor(repo='.', stall_timeout=3600)
        self.sup.bus=self.bus
        # start from the real counter, not a shadow attribute
        self.sup._routing_failure_count = 0
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
        # two CONSECUTIVE null-turn states must actually reach escalation
        self.bus.state_data.update({'status':'running','turn':None})
        self.sup._check_stall(self.bus.state())
        # first null reissued the turn; simulate the next observed state still null
        self.bus.state_data['turn']=None
        self.sup._check_stall(self.bus.state())
        # both null observations logged a routing-failure
        count=sum(1 for _,k,_ in self.bus.logs if k=='routing-failure')
        self.assertEqual(count,2)
        # escalation really happened: a gate was opened
        self.assertGreaterEqual(len(self.bus.opened_gates),1)
    def test_routing_failure_counter_resets_on_valid_turn(self):
        # null, valid turn, null -> count back at 1, no escalation
        self.bus.state_data.update({'status':'running','turn':None})
        self.sup._check_stall(self.bus.state())
        self.assertEqual(self.sup._routing_failure_count,1)
        # valid running turn observed -> counter resets
        self.bus.state_data.update({'status':'running','turn':'coordinator',
            'turn_since':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        self.sup._check_stall(self.bus.state())
        self.assertEqual(self.sup._routing_failure_count,0)
        # next null counts from 1 again: reissue, no escalation gate
        self.bus.state_data['turn']=None
        self.sup._check_stall(self.bus.state())
        self.assertEqual(self.sup._routing_failure_count,1)
        self.assertEqual(len(self.bus.opened_gates),0)
    def test_done_no_action(self):
        self.bus.state_data.update({'status':'done','turn':None})
        self.sup._check_stall(self.bus.state())
        self.assertEqual(len(self.bus.logs),0)
    def test_done_null_no_routing_failure(self):
        # regression: status done with null turn is a valid terminal state,
        # it must never enter the routing-failure path
        self.bus.state_data.update({'status':'done','turn':None})
        self.sup._check_stall(self.bus.state())
        self.assertFalse(any(k=='routing-failure' for _,k,_ in self.bus.logs))
        self.assertEqual(getattr(self.sup,'_routing_failure_count',0),0)
        self.assertEqual(len(self.bus.opened_gates),0)

if __name__=='__main__':
    unittest.main()
