import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from datetime import datetime


class DateAndTimeCapability(MatchingCapability):
    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(
        self,
        worker: AgentWorker,
    ):
        msg = worker.final_user_input
        final_prompt = ""
        now = datetime.now()

        if msg.find("date") != -1:
            date_right_now = now.strftime("%A %d %B %Y")  # , %H:%M:%S")
            final_prompt += "Date is " + date_right_now

        if msg.find("time") != -1:
            time_right_now = now.strftime("%H:%M:%S")
            final_prompt += "\nTime is " + time_right_now

        return final_prompt
