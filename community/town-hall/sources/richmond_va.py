from .legistar import LegistarCitySource


class RichmondCitySource(LegistarCitySource):
    """richmond city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="richmondva",
            display_name="Richmond City Council",
            trigger_keywords=("richmond",),
            priority_bodies=("City Council",),
            legislation_name="Richmond City Legislation",
        )
