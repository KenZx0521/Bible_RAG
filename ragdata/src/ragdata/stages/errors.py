"""Errors that stop a build stage: its output could not be trusted, so none is produced."""


class StageError(RuntimeError):
    """A stage met input it cannot turn into trustworthy records."""


class ParseError(StageError):
    """The page does not have the structure the parser relies on (book, page, row named)."""
