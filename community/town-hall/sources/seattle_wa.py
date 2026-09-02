from .legistar import LegistarCitySource


class SeattleCitySource(LegistarCitySource):
    """seattle city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="seattle",
            display_name="Seattle City Council",
            trigger_keywords=("seattle",),
            priority_bodies=("City Council",),
            matter_type_names=(
                "Ordinance (Ord)",
                "Resolution (Res)",
                "Council Bill (CB)",
            ),
            legislation_name="Seattle City Legislation",
        )
