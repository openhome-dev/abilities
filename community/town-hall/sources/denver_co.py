from .legistar import LegistarCitySource


class DenverCitySource(LegistarCitySource):
    """denver city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="denver",
            display_name="Denver City Council",
            trigger_keywords=("denver",),
            priority_bodies=("City Council",),
            matter_type_names=("Resolution", "Bill"),
            legislation_name="Denver City Legislation",
        )
