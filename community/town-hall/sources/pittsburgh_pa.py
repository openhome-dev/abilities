from .legistar import LegistarCitySource


class PittsburghCitySource(LegistarCitySource):
    """pittsburgh city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="pittsburgh",
            display_name="Pittsburgh City Council",
            trigger_keywords=("pittsburgh",),
            priority_bodies=("City Council",),
            legislation_name="Pittsburgh City Legislation",
        )
