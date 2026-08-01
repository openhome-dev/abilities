from .legistar import LegistarCitySource


class OaklandCitySource(LegistarCitySource):
    """oakland city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="oakland",
            display_name="Oakland City Council",
            trigger_keywords=("oakland",),
            priority_bodies=("City Council",),
            matter_type_names=("Ordinance", "City Resolution", "ORSA Ordinance"),
            legislation_name="Oakland City Legislation",
        )
