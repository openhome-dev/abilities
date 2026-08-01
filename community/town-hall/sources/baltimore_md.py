from .legistar import LegistarCitySource


class BaltimoreCitySource(LegistarCitySource):
    """baltimore city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="baltimore",
            display_name="Baltimore City Council",
            trigger_keywords=("baltimore",),
            priority_bodies=("Baltimore City Council", "City Council"),
            matter_type_names=("Ordinance", "City Council Resolution"),
            legislation_name="Baltimore City Legislation",
        )
