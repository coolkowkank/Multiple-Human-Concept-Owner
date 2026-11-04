import json
import os
import tempfile
import unittest
from unittest.mock import patch
from launcher import prompts
from launcher.prompt_audit import audit_parts, render_audited_prompt, PromptAuditAdapter


class PromptAuditTests(unittest.TestCase):
    def render(self, **changes):
        data = dict(seat='builder', role='builder', brief='add(a,b)',
                    state={'turn_seq': 7, 'status_line': 'working'},
                    recent_log=[{'ts': '2026-11-04', 'seat': 'qc',
                                 'kind': 'handoff', 'body': 'check exact pin'}],
                    batch='one file')
        data.update(changes)
        result = render_audited_prompt(**data)
        self.assertEqual(result[0], prompts.system_prompt(data['role']))
        self.assertEqual(result[1], prompts.task_prompt(**data))
        return result

    def test_exact_coverage(self):
        system, task, report = self.render()
        for text, key in [(system, 'system'), (task, 'task')]:
            rows = report[key]['sources']
            self.assertEqual(rows[0]['start_char'], 0)
            self.assertEqual(rows[-1]['end_char'], len(text))
            self.assertEqual(sum(r['chars'] for r in rows), len(text))
            for a, b in zip(rows, rows[1:]):
                self.assertEqual(a['end_char'], b['start_char'])
        self.assertIsNone(report['provider_tokens'])

    def test_no_history_no_batch_and_empty_brief(self):
        self.render(recent_log=[], batch=None, brief='')
        self.render(recent_log=[], batch='', brief=None)

    def test_missing_state_fields_and_log_fields(self):
        self.render(state={}, recent_log=[{}])

    def test_unicode_and_delimiter_like_content(self):
        _, _, report = self.render(brief='é🙂\n# Recent coordination log',
                                   batch='\n# Agreed brief')
        row = report['task']['sources'][1]
        self.assertGreater(row['utf8_bytes'], row['chars'])

    def test_role_contract_preserved_for_every_role(self):
        for role in prompts.ROLES:
            self.render(role=role)

    def test_renderer_drift_refused(self):
        with patch.object(prompts, 'task_prompt', return_value='changed'):
            with self.assertRaises(ValueError):
                self.render()

    def test_missing_or_overlapping_sources_refused(self):
        for parts in [[('brief', 'a')], [('x', 'ab'), ('y', 'b')]]:
            with self.assertRaises(ValueError):
                audit_parts(parts, 'ab')

    def test_report_does_not_copy_prompt_content(self):
        _, _, report = self.render(brief='UNIQUE_PRIVATE_PAYLOAD')
        self.assertNotIn('UNIQUE_PRIVATE_PAYLOAD', json.dumps(report))

    def test_estimate_is_labelled_and_not_source_token_attribution(self):
        report = audit_parts([('a', 'a'), ('b', 'bcd')], 'abcd')
        self.assertEqual(report['est_tokens_chars_div_4'], 1)
        self.assertTrue(all('tokens' not in row for row in report['sources']))


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'audit.jsonl')
        self.context = dict(seat='builder', role='builder', brief='test',
                            state={}, recent_log=[])
        self.system, self.task, _ = render_audited_prompt(**self.context)
        self.inner = unittest.mock.Mock()
        self.inner.complete.return_value = {'handoff': 'reviewer'}
        self.wrapper = PromptAuditAdapter(self.inner, self.path, lambda: self.context)

    def rows(self):
        with open(self.path) as fh:
            return [json.loads(line) for line in fh]

    def test_actual_call_inputs_unchanged(self):
        result = self.wrapper.complete(self.system, self.task)
        self.inner.complete.assert_called_once_with(self.system, self.task)
        self.assertEqual(result, {'handoff': 'reviewer'})
        rows = self.rows()
        self.assertEqual([r['event'] for r in rows],
                         ['adapter_call_start', 'adapter_call_returned'])
        self.assertEqual(rows[0]['call_id'], rows[1]['call_id'])

    def test_error_recorded_and_raised_without_retry(self):
        self.inner.complete.side_effect = RuntimeError('private content')
        with self.assertRaises(RuntimeError):
            self.wrapper.complete(self.system, self.task)
        self.assertEqual(self.inner.complete.call_count, 1)
        self.assertEqual(self.rows()[-1]['event'], 'adapter_call_error')
        with open(self.path) as fh:
            self.assertNotIn('private content', fh.read())

    def test_mismatched_context_never_calls_inner(self):
        with self.assertRaises(ValueError):
            self.wrapper.complete(self.system, self.task + 'unaccounted')
        self.inner.complete.assert_not_called()
        self.assertFalse(os.path.exists(self.path))

    def test_start_record_failure_never_calls_inner(self):
        with patch.object(self.wrapper, '_record', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.wrapper.complete(self.system, self.task)
        self.inner.complete.assert_not_called()

    def test_correction_is_another_recorded_adapter_call(self):
        self.wrapper.complete(self.system, self.task)
        self.context['correction_suffix'] = '\nCORRECTION: exact JSON'
        self.wrapper.complete(self.system, self.task + self.context['correction_suffix'])
        starts = [r for r in self.rows() if r['event'] == 'adapter_call_start']
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]['call_id'], starts[1]['call_id'])
        self.assertEqual(starts[1]['audit']['task']['sources'][-1]['source'],
                         'correction_suffix')

    def test_consume_delegated_once(self):
        self.wrapper.consume()
        self.inner.consume.assert_called_once_with()

    def test_post_call_log_failure_is_not_retried(self):
        with patch.object(self.wrapper, '_record', side_effect=[None, OSError('disk')]):
            with self.assertRaises(OSError):
                self.wrapper.complete(self.system, self.task)
        self.assertEqual(self.inner.complete.call_count, 1)


if __name__ == '__main__':
    unittest.main()
