import contextlib
import io
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from voice_to_doc import Workflow, export_approved, parse_fields, review, run_demo


ORDER = """SYNTHETIC
Note type: order
Caller: SYNTHETIC_TEAM_ALPHA
Order: Blue sample bags
Qty: 12 pieces
Tareekh: 2026-11-20
Agla kaam: Check packing.
Action: Send the packing list.
"""


class VoiceToDocTests(unittest.TestCase):
    def test_extract_mixed_labels_and_actions(self):
        self.assertEqual(parse_fields(ORDER), {
            'note type': ['order'],
            'who': ['SYNTHETIC_TEAM_ALPHA'],
            'what': ['Blue sample bags'],
            'quantity': ['12 pieces'],
            'date': ['2026-11-20'],
            'action': ['Check packing.', 'Send the packing list.'],
        })

    def test_flags_missing_and_unclear_values(self):
        flow = Workflow('SYNTHETIC\nNote type: order\nWho: TBD\nDate: next Friday\n')
        self.assertEqual(flow.status, 'waiting_for_details')
        self.assertCountEqual(flow.issues, [
            'what: missing', 'action: missing', 'quantity: missing', 'who: unclear',
            'date: use an exact YYYY-MM-DD date',
        ])
        self.assertIn('## Review flags', flow.draft())
        with self.assertRaisesRegex(ValueError, 'Approval blocked'):
            flow.approve()

    def test_conflicting_dates_require_a_correction(self):
        flow = Workflow(ORDER + 'Date: 2026-11-21\n')
        self.assertIn('date: multiple values, choose one', flow.issues)
        flow.correct('date', '2026-11-21')
        self.assertEqual(flow.status, 'waiting_for_approval')

    def test_meeting_does_not_require_quantity(self):
        flow = Workflow('SYNTHETIC\nNote type: meeting\nWho: SYNTHETIC_TEAM_BETA\n'
                        'Topic: Packing plan\nDate: 2026-11-19\nAction: Review packing.\n')
        flow.approve()
        self.assertTrue(flow.draft().startswith('# Meeting note\n'))
        self.assertNotIn('Quantity', flow.draft())

    def test_correction_requires_reapproval_before_export(self):
        flow = Workflow(ORDER)
        flow.approve()
        flow.correct('quantity', '14 pieces')
        self.assertEqual(flow.status, 'waiting_for_approval')
        with TemporaryDirectory() as folder:
            destination = Path(folder) / 'exports'
            self.assertEqual(export_approved({'order': flow}, destination), [])
            self.assertFalse(destination.exists())
            flow.approve()
            path, = export_approved({'order': flow}, destination)
            markdown = path.read_text(encoding='utf-8')
            self.assertIn('14 pieces', markdown)
            self.assertNotIn('12 pieces', markdown)

    def test_export_excludes_pending_and_incomplete_drafts(self):
        approved = Workflow(ORDER)
        approved.approve()
        documents = {
            'approved': approved,
            'pending': Workflow(ORDER),
            'incomplete': Workflow('SYNTHETIC\nNote type: meeting\n'),
        }
        with TemporaryDirectory() as folder:
            path, = export_approved(documents, Path(folder))
            self.assertEqual(list(path.parent.iterdir()), [path])
            self.assertEqual(path.name, 'approved.md')
            self.assertIn('**SYNTHETIC**', path.read_text(encoding='utf-8'))

    def test_human_review_can_approve_edit_and_reapprove(self):
        flow = Workflow(ORDER)
        with patch('builtins.input', side_effect=['approve', 'quantity: 16 pieces', 'approve', 'next']):
            with contextlib.redirect_stdout(io.StringIO()):
                review(flow)
        self.assertEqual(flow.status, 'approved')
        self.assertIn('16 pieces', flow.draft())

    def test_scripted_demo_runs_offline(self):
        with TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            with patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
                path, = run_demo(Path(folder))
            self.assertEqual(path.name, 'order.md')
            self.assertIn('14 pieces', path.read_text(encoding='utf-8'))
        self.assertIn('Approval blocked', output.getvalue())
        self.assertIn('SIMULATED REVIEWER: re-approved', output.getvalue())


if __name__ == '__main__':
    unittest.main()
