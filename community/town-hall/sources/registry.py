from .virginia_state import VirginiaStateSource
from .richmond_va import RichmondCitySource
from .seattle_wa import SeattleCitySource
from .oakland_ca import OaklandCitySource
from .boston_ma import BostonCitySource
from .denver_co import DenverCitySource
from .baltimore_md import BaltimoreCitySource
from .phoenix_az import PhoenixCitySource
from .pittsburgh_pa import PittsburghCitySource
from .sanjose_ca import SanJoseCitySource


def discover_sources():
    """return all registered civic sources.
    to add a locality: implement CivicSource in a new module, then append
    an instance below — no auto-import (openhome forbids importlib)."""
    return [
        VirginiaStateSource(),
        RichmondCitySource(),
        SeattleCitySource(),
        OaklandCitySource(),
        BostonCitySource(),
        DenverCitySource(),
        BaltimoreCitySource(),
        PhoenixCitySource(),
        PittsburghCitySource(),
        SanJoseCitySource(),
    ]
