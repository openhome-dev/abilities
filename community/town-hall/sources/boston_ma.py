from .legistar import LegistarCitySource


class BostonCitySource(LegistarCitySource):
    """boston city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="boston",
            display_name="Boston City Council",
            trigger_keywords=("boston",),
            priority_bodies=("City Council", "Boston City Council"),
            matter_type_names=(
                "Council Ordinance",
                "Mayor Ordinance",
                "Council Legislative Resolution",
                "Consent Agenda Resolution",
            ),
            legislation_name="Boston City Legislation",
        )
