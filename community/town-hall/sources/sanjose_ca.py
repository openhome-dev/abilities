from .legistar import LegistarCitySource


class SanJoseCitySource(LegistarCitySource):
    """san jose city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="sanjose",
            display_name="San Jose City Council",
            trigger_keywords=("san jose", "sanjose"),
            priority_bodies=("City Council",),
            matter_type_names=("Resolution", "Final Adoption of Ordinance"),
            legislation_name="San Jose City Legislation",
        )
