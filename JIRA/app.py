import base64
import datetime
import logging
import logging.handlers
import os.path
import threading
import time

import pytmv1
import yaml
from pytmv1 import EntityType, InvestigationStatus, ResultCode
from requests import Request, Session

ALERT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
ADD_ATTACHMENT = "/rest/api/2/issue/{0}/attachments"
CREATE_ISSUE = "/rest/api/2/issue"
DO_TRANSITION = "/rest/api/2/issue/{0}/transitions"
GET_ISSUE = "/rest/api/2/issue/{0}"
GET_LAST_UPDATED = "/rest/api/2/issue/{0}?fields=creator,updated"
GET_STATUS = "/rest/api/2/issue/{0}?fields=status"
GET_TRANSITIONS = "/rest/api/2/issue/{0}/transitions"
LOG_FORMAT = (
    "%(asctime)s %(levelname)-5s ::: %(thread)d %(filename)-18s :::"
    " %(funcName)-18s:%(lineno)-5s ::: %(id)s :::  %(message)s"
)
LOG_FORMAT_DATE = "%Y-%m-%d %H:%M:%S"

_THREAD_LOCAL = threading.local()

log = logging.getLogger(__name__)


class App:
    def __init__(self):
        self._load_config()
        self.init_logger()
        self._load_cache()
        self.v_client = pytmv1.client(
            "v1jira",
            self._config["v1"]["token"],
            self._config["v1"]["url"],
            1,
            1,
            30,
            30,
        )
        self.j_client = Session()
        # self.j_client = adapters.HTTPAdapter(1, 1, 0, True)
        log.info("Initialized application with config: %s", self._config)

    def init_logger(self):
        handler: logging.Handler
        if self._config["app"]["log"]["to_file"]:
            handler = logging.handlers.RotatingFileHandler(
                self._config["app"]["log"]["filename"],
                maxBytes=int(self._config["app"]["log"]["file_size"]) * 1024 * 1024,
                backupCount=self._config["app"]["log"]["file_count"],
            )
        else:
            handler = logging.StreamHandler()
        formatter = logging.Formatter(LOG_FORMAT, LOG_FORMAT_DATE)
        handler.setFormatter(formatter)
        handler.addFilter(UuidFilter())
        root = logging.getLogger()
        root.setLevel(
            logging.DEBUG if self._config["app"]["log"]["debug"] else logging.INFO
        )
        root.addHandler(handler)

    def run(self):
        while True:
            alert_list = []
            start_time = (
                self._config["app"]["alert"]["start_time"].strftime(ALERT_DATE_FORMAT)
                if self._config["app"]["alert"]["start_time"]
                else None
            )
            end_time = (
                self._config["app"]["alert"]["end_time"].strftime(ALERT_DATE_FORMAT)
                if self._config["app"]["alert"]["end_time"]
                else None
            )
            log.info(
                "Fetching alerts from Vision One [start_time: %s, end_time: %s, skip_closed: %s]",
                start_time,
                end_time,
                self._config["app"]["alert"]["skip_closed"],
            )
            result = self.v_client.consume_alert_list(
                lambda al: alert_list.append(al)
                if (
                    self._config["app"]["alert"]["skip_closed"]
                    and al.investigation_status != InvestigationStatus.CLOSED
                    or al.id in self._cache
                )
                or not self._config["app"]["alert"]["skip_closed"]
                else None,
                start_time,
                end_time,
            )
            log.debug("Fetched alerts from Vision One: %s", alert_list)
            if result.result_code == ResultCode.SUCCESS:
                if len(alert_list) > 0:
                    log.info(
                        "Start processing %s alerts from Vision One",
                        len(alert_list),
                    )
                    for alert in alert_list:
                        _THREAD_LOCAL.id = alert.id
                        self._update_status(
                            alert
                        ) if alert.id in self._cache else self._create_jira(alert)
                        log.info(
                            "Finished processing alert (%s)", self._cache[alert.id]
                        )
                    _THREAD_LOCAL.id = "App"
                    log.info("Total processed: %s", len(alert_list))
                else:
                    log.info("No records found in Vision One: %s", result.response)
            else:
                log.error("Could not fetch alerts from Vision One: %s", result.error)
            time.sleep(self._config["app"]["poll_time"])

    def _load_config(self):
        with open("config.yml", "r") as stream:
            try:
                config = yaml.safe_load(stream)
                self._config = config
            except yaml.YAMLError as exc:
                logging.critical("Could not load config file: %s", exc)
                exit(500)

    def _load_cache(self):
        try:
            if os.path.isfile(".cache"):
                with open(".cache", "rt") as cache:
                    self._cache = {
                        k.split(":")[0]: k.split(":")[1]
                        for k in cache.read().split(",")
                        if k
                    }
                    log.info("Loaded cache: %s", self._cache)
            else:
                open(".cache", "x").close()
                self._cache = {}
                log.info("Created new empty cache file [.cache]")
        except OSError as exc:
            log.critical("Could not load cache file: %s", exc)
            log.critical("Exiting")
            exit(500)

    def _save_cache(self, alert_id, jira_id):
        try:
            with open(".cache", "a") as cache:
                cache.write(alert_id + ":" + jira_id + ",")
                self._cache[alert_id] = jira_id
                log.debug("Written to cache alert %s (%s)", alert_id, jira_id)
        except OSError as exc:
            log.critical("Could not save to cache: %s", exc)
            log.critical("Exiting")
            exit(500)

    def _create_jira(self, alert):
        log.info("Not found in cache, creating issue")
        response = self.j_client.send(
            self._request("POST", CREATE_ISSUE, json=self._jira_map(alert)).prepare(),
            timeout=(60, 10),
        )
        log.debug("Received response from JIRA: %s", response)
        if response.status_code == 201:
            log.info("JIRA issue created: %s", response.json()["key"])
            self._save_cache(alert.id, response.json()["key"])
            attachment_response = self.j_client.send(
                self._request(
                    "POST",
                    ADD_ATTACHMENT.format(self._cache[alert.id]),
                    headers={"X-Atlassian-Token": "no-check"},
                    files={
                        "file": (
                            "json.txt",
                            alert.json(),
                            "text/plain",
                        )
                    },
                ).prepare()
            )
            log.debug("Received response from JIRA: %s", attachment_response)
            if attachment_response.status_code == 200:
                log.info("Attached json data to issue")
            else:
                log.error(
                    "Could not attach raw json data to issue %s: %s",
                    self._cache[alert.id],
                    attachment_response,
                )
            log.debug("Adding Vision One alert note")
            response = self.v_client.add_alert_note(
                alert.id,
                f"JIRA Incident Created: {response.json()['key']}\n"
                f"URL: {self._config['jira']['url'] + '/browse/' + response.json()['key']}",
            )
            log.debug("Received response from Vision One: %s", response)
            if response.result_code == ResultCode.SUCCESS:
                log.info("Created Vision One note: %s", response.response.location)
            else:
                log.error("Could not create Vision One note: %s", response.error)
        else:
            log.error(
                "Could not create JIRA issue: %s",
                response.text,
            )

    def _get_jira_status(self, alert):
        log.debug("Fetching current JIRA status for issue: %s", self._cache[alert.id])
        status_response = self.j_client.send(
            self._request("GET", GET_STATUS.format(self._cache[alert.id])).prepare(),
            timeout=(60, 10),
        )
        log.debug("Received response from JIRA: %s", status_response)
        if status_response.status_code == 200:
            return status_response.json()["fields"]["status"]["name"]
        else:
            log.error("Could not fetch JIRA issue: %s", status_response.text)

    def _is_status_mapped(self, jira_status, v1_status):
        is_v1_status_mapped = (
            next(
                filter(
                    lambda status: status["value"] == v1_status,
                    self._config["jira"]["status"],
                ),
                None,
            )
            is not None
        )
        is_jira_status_mapped = (
            next(
                filter(
                    lambda status: status["key"].lower() == jira_status.lower(),
                    self._config["jira"]["status"],
                ),
                None,
            )
            is not None
        )
        return is_v1_status_mapped and is_jira_status_mapped

    def _update_status(self, alert):
        log.info("Found in cache, starting update")
        jira_status = self._get_jira_status(alert)
        if not self._is_status_mapped(jira_status, alert.investigation_status.value):
            log.warning(
                "JIRA or Vision One status not found in configuration, jira status: %s, v1 status: %s, config: %s",
                jira_status,
                alert.investigation_status.value,
                self._config["jira"]["status"],
            )
            log.warning("Skipping update")
            return
        jira_status_map = next(
            filter(
                lambda status: jira_status.lower() == status["key"].lower(),
                self._config["jira"]["status"],
            )
        )
        if jira_status_map["value"] != alert.investigation_status.value:
            log.info(
                "Statuses not equal, JIRA status: %s, Vision One status: %s",
                jira_status,
                alert.investigation_status.value,
            )
            log.info("Comparing last updated time")
            last_updated_response = self.j_client.send(
                self._request(
                    "GET", GET_LAST_UPDATED.format(self._cache[alert.id])
                ).prepare(),
                timeout=(60, 10),
            )
            log.debug("Received response from JIRA: %s", last_updated_response)

            if last_updated_response.status_code == 200:
                last_jira_update = datetime.datetime.strptime(
                    last_updated_response.json()["fields"]["updated"][:19]
                    + last_updated_response.json()["fields"]["updated"][23:28],
                    "%Y-%m-%dT%H:%M:%S%z",
                ).astimezone(datetime.timezone.utc)
                last_v1_update = datetime.datetime.strptime(
                    alert.updated_date_time[:-1] + "+00:00:00", "%Y-%m-%dT%H:%M:%S%z"
                )
                if last_jira_update > last_v1_update:
                    log.info("JIRA updated after Vision One")
                    investigation_status = InvestigationStatus(jira_status_map["value"])
                    log.debug("Fetching ETag from Vision One")
                    get_alert_detail = self.v_client.get_alert_details(alert.id)
                    log.debug("Received response from Vision One: %s", get_alert_detail)
                    if get_alert_detail.result_code == ResultCode.SUCCESS:
                        log.debug("Editing Vision One alert status")
                        edit_status = self.v_client.edit_alert_status(
                            alert.id,
                            investigation_status,
                            get_alert_detail.response.etag,
                        )
                        log.debug("Received response from Vision One: %s", edit_status)
                        if edit_status.result_code == ResultCode.SUCCESS:
                            log.info(
                                "Updated Vision One Alert (%s) status to: %s",
                                self._cache[alert.id],
                                investigation_status.value,
                            )
                        else:
                            log.error(
                                "Could not update Vision One Alert (%s) status: %s",
                                self._cache[alert.id],
                                edit_status.error,
                            )
                    else:
                        log.error(
                            "Could not fetch ETag from Vision One (%s): %s",
                            self._cache[alert.id],
                            get_alert_detail.error,
                        )
                if last_v1_update > last_jira_update:
                    log.info("Vision One updated after JIRA")
                    transitions_response = self.j_client.send(
                        self._request(
                            "GET", GET_TRANSITIONS.format(self._cache[alert.id])
                        ).prepare(),
                        timeout=(60, 10),
                    )
                    log.debug("Received response from JIRA: %s", transitions_response)
                    if transitions_response.status_code == 200:
                        v1_status_map = next(
                            filter(
                                lambda status: alert.investigation_status.value
                                == status["value"],
                                self._config["jira"]["status"],
                            )
                        )
                        transition = next(
                            filter(
                                lambda trans: v1_status_map["key"]
                                == trans["to"]["name"].strip(),
                                transitions_response.json()["transitions"],
                            )
                        )
                        json = {}
                        if v1_status_map.get("fields") is not None:
                            json = {"fields": {}}
                            for field in v1_status_map.get("fields"):
                                json["fields"][field.get("key")] = {
                                    field.get("type")
                                    if field.get("type")
                                    else "id": str(field.get("value"))
                                }
                        json["transition"] = {"id": transition["id"]}
                        do_transition_response = self.j_client.send(
                            self._request(
                                "POST",
                                DO_TRANSITION.format(self._cache[alert.id]),
                                json=json,
                            ).prepare(),
                            timeout=(60, 10),
                        )
                        log.debug(
                            "Received response from JIRA: %s", do_transition_response
                        )
                        if do_transition_response.status_code == 204:
                            log.info(
                                "Updated JIRA issue: %s, status to: %s",
                                self._cache[alert.id],
                                v1_status_map["key"],
                            )
                        else:
                            log.error(
                                "Could not update JIRA issue status: %s",
                                do_transition_response.text,
                            )
                    else:
                        log.error(
                            "Could not fetch JIRA possible transitions: %s",
                            transitions_response.text,
                        )
            else:
                log.error(
                    "Could not fetch JIRA last updated time: %s",
                    last_updated_response.text,
                )
        else:
            log.debug(
                "Statuses are equal, jira status: %s, v1 status: %s",
                jira_status,
                alert.investigation_status.value,
            )
            log.debug("Skipping update")

    def _map_value(self, field_type, value, dynamic, alert):
        parsed = [
            str(getattr(alert, val.strip())) if dynamic else val.strip()
            for val in str(value).split(",")
        ]
        if field_type == "array":
            return parsed
        parsed_string = " ".join(parsed)
        if field_type == "string":
            return parsed_string
        return {field_type: parsed_string}

    def _jira_map(self, alert):
        host_entities = list(
            filter(
                lambda ent: ent.entity_type == EntityType.HOST,
                alert.impact_scope.entities,
            )
        )
        prefix = self._config["jira"]["fields"]["summary_prefix"]
        body = {
            "fields": {
                "summary": (prefix + " | " if prefix else "")
                + alert.id
                + " | "
                + alert.model
                + " | "
                + (
                    "Multiple Hosts"
                    if len(host_entities) > 1
                    else host_entities[0].entity_value.name
                ),
                "description": self._format_description(alert),
            }
        }
        for field in self._config["jira"]["fields"]["static"]:
            body["fields"][field.get("key")] = self._map_value(
                field.get("type"), field.get("value"), False, None
            )
        for field in self._config["jira"]["fields"]["dynamic"]:
            if field.get("mapping") is not None:
                field_value = next(
                    filter(
                        lambda k: next(
                            filter(
                                lambda kn: kn.strip()
                                == getattr(alert, field.get("value")),
                                k[1].split(","),
                            ),
                            False,
                        ),
                        field.get("mapping").items(),
                    )
                )[0]
                body["fields"][field.get("key")] = self._map_value(
                    field.get("type"), field_value, False, None
                )
                continue
            body["fields"][field.get("key")] = self._map_value(
                field.get("type"), field.get("value"), True, alert
            )
        log.debug("Mapped alert to JIRA Issue: %s", body)
        return body

    def _format_description(self, alert):
        rules = "\n** ".join(rule.name for rule in alert.matched_rules)
        entities = "\n** ".join(
            entity.entity_type
            + ": "
            + (
                entity.entity_value
                if isinstance(entity.entity_value, str)
                else entity.entity_value.name
                + " ("
                + entity.entity_value.guid
                + ") - "
                + ",".join(entity.entity_value.ips)
            )
            for entity in alert.impact_scope.entities
        )
        indicators = "\n** ".join(
            indicator.type
            + ": "
            + (
                indicator.value
                if isinstance(indicator.value, str)
                else indicator.value.name
                + " ("
                + indicator.value.guid
                + ") - "
                + ",".join(indicator.value.ips)
            )
            for indicator in alert.indicators
        )
        mitres = []
        for rule in alert.matched_rules:
            for filter in rule.matched_filters:
                for tech in filter.mitre_technique_ids:
                    mitres.append(tech)
        mitres = "\n** ".join(mitres)
        return (
            f"*Summary*\n\n* Detected by: XDR\n* Severity: {alert.severity}\n* Score: {alert.score}\n\n\n"
            f"*Event Details*\n\n* Vision One Model: {alert.model}\n* Rules\n** {rules}\n"
            f"* Vision One Alert Highlights:\n** {entities}\n"
            f"* Vision One Alert Indicators\n** {indicators}\n"
            f"* MITRE ATT&CK:\n** {mitres}\n"
            f"* Vision One Alert Link:\n** {alert.workbench_link}"
        )

    def _request(self, method, uri, **kwargs):
        token = self._config["jira"]["token"]
        username = self._config["jira"]["username"]
        authorization = (
            f"Basic {base64.b64encode('{}:{}'.format(username, token).encode()).decode()}"
            if username
            else f"Bearer {token}"
        )
        headers = {"Authorization": authorization}
        headers.update(kwargs.pop("headers", {}))
        return Request(
            method,
            self._config["jira"]["url"] + uri,
            headers=headers,
            **kwargs,
        )


class UuidFilter(logging.Filter):
    def filter(self, record):
        record.id = (
            _THREAD_LOCAL.id if hasattr(_THREAD_LOCAL, "id") and not None else "App"
        )
        return True


if __name__ == "__main__":
    app = App()
    app.run()
