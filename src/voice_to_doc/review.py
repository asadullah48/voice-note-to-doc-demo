"""Review workflow: corrections clear approval; approval is blocked while flags remain."""
from .draft import render, validate
from .extract import FIELDS, parse_fields


class Workflow:
    def __init__(self, transcript):
        self._fields = parse_fields(transcript)
        self._approved = None

    @property
    def issues(self):
        return validate(self._fields)

    @property
    def status(self):
        if self._approved is not None:
            return 'approved'
        return 'waiting_for_details' if self.issues else 'waiting_for_approval'

    def draft(self):
        return render(self._fields, self.issues)

    def correct(self, field, value):
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type') or not value or len(value.splitlines()) != 1:
            raise ValueError('Use a supported field and a single non-empty line')
        self._fields[field] = [value]
        self._approved = None

    def approve(self):
        if self.issues:
            raise ValueError('Approval blocked until the review flags are resolved')
        self._approved = self.draft()


def review(flow):
    while True:
        print(flow.draft())
        print('Review status:', flow.status)
        command = input('Approve, edit (field: value), or next? ').strip()
        try:
            if command == 'next':
                return
            if command == 'approve':
                flow.approve()
            elif ':' in command:
                flow.correct(*command.split(':', 1))
            else:
                print('Enter approve, field: value, or next.')
        except ValueError as error:
            print(error)
