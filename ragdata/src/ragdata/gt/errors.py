"""The exceptions by which GT v2 tooling reports bad input (the CLI exits 2 on them)."""

from ragcommon.refs import RefParseError
from ragcommon.versification import VersificationError
from ragdata.gt.build import BuildError
from ragdata.gt.changes import ChangeError
from ragdata.gt.cli import GtCliError
from ragdata.gt.corpus import CorpusError
from ragdata.gt.curated import CuratedError
from ragdata.gt.goldrefs import GoldError
from ragdata.gt.mechanical import MechanicalError
from ragdata.gt.rules import RuleError
from ragdata.gt.textnorm import QuoteError

GT_ERRORS = (BuildError, ChangeError, GtCliError, CorpusError, CuratedError, GoldError,
             MechanicalError, RuleError, QuoteError, RefParseError, VersificationError)
