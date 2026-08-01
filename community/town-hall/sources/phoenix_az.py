from .legistar import LegistarCitySource


class PhoenixCitySource(LegistarCitySource):
    """phoenix city council - meetings and legislation via legistar web api."""

    def __init__(self):
        super().__init__(
            client_id="phoenix",
            display_name="Phoenix City Council",
            trigger_keywords=("phoenix",),
            priority_bodies=("City Council",),
            matter_type_names=(
                "Resolution",
                "Ordinance-G",
                "Ordinance-S",
                "Zoning Ordinance",
                "Payment Ordinance",
                "Ordinance - S Consolidated",
            ),
            legislation_name="Phoenix City Legislation",
        )
