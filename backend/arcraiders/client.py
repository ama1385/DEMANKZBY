from functools import cache
import json
from urllib import error
from urllib import parse
from urllib import request

from arcraiders.auth import TokenAuth
from arcraiders.auth.base import Auth
from arcraiders.config import API_BASE_URL
from arcraiders.config import MANIFEST_APP_ID
from arcraiders.config import MANIFEST_BUILD_ID
from arcraiders.config import MANIFEST_STORE_DEPLOYMENT_TARGET
from arcraiders.config import USER_AGENT
from arcraiders.endpoints import ANNOUNCEMENTS
from arcraiders.endpoints import ANTICHEAT_RESTRICTIONS
from arcraiders.endpoints import BATTLEPASS_LIST_BATTLEPASSES
from arcraiders.endpoints import BONUSES
from arcraiders.endpoints import CODEX_ENTRIES
from arcraiders.endpoints import COMMUNITY_EVENT
from arcraiders.endpoints import COMPENSATIONS
from arcraiders.endpoints import DISTRIBUTION_PLATFORM_ACHIEVEMENTS_GET
from arcraiders.endpoints import Endpoint
from arcraiders.endpoints import EXPEDITIONS
from arcraiders.endpoints import GAME_DATA
from arcraiders.endpoints import GAME_DATA_STORE
from arcraiders.endpoints import GAME_SETTINGS
from arcraiders.endpoints import GET_PERSISTENT_PLAYER_KEYS
from arcraiders.endpoints import HEARTBEAT
from arcraiders.endpoints import INBOX_GET_MESSAGES
from arcraiders.endpoints import INVENTORY
from arcraiders.endpoints import INVENTORY_MUTATE
from arcraiders.endpoints import LEAGUE
from arcraiders.endpoints import LEVELS_AUTO_CLAIM
from arcraiders.endpoints import LEVELS_LIST
from arcraiders.endpoints import LOCALIZATIONS
from arcraiders.endpoints import MANIFEST
from arcraiders.endpoints import MASTERY_OBJECTIVES
from arcraiders.endpoints import NOTIFICATIONS
from arcraiders.endpoints import PLAYER_ACTIVITY
from arcraiders.endpoints import PROFILE
from arcraiders.endpoints import PROFILE_BY_THIRDPARTY_USERID
from arcraiders.endpoints import PROJECTS_LIST
from arcraiders.endpoints import PROXY
from arcraiders.endpoints import QUILKIN
from arcraiders.endpoints import QUESTS
from arcraiders.endpoints import QUESTS_RECONCILE
from arcraiders.endpoints import QUESTS_REROLL_COST
from arcraiders.endpoints import RAIDERS
from arcraiders.endpoints import RANK_LIST
from arcraiders.endpoints import SCENARIOS
from arcraiders.endpoints import SEASONAL_REWARDS
from arcraiders.endpoints import SET_PERSISTENT_PLAYER_KEYS
from arcraiders.endpoints import SOCIAL_BLOCKED_PLAYERS
from arcraiders.endpoints import SOCIAL_FRIENDS_GET
from arcraiders.endpoints import SOCIAL_PARTY_GET
from arcraiders.endpoints import SOCIAL_PARTY_UPDATE_PARTY_MEMBER_DATA
from arcraiders.endpoints import SOCIAL_PRESENCE_GET
from arcraiders.endpoints import SOCIAL_PRESENCE_SET_RICH_PRESENCE
from arcraiders.endpoints import SOCIAL_RECENTLY_PLAYED_WITH
from arcraiders.endpoints import STATS_PLAYER_V2
from arcraiders.endpoints import STORE_GET_MICROSOFT_STORE_ACCESS_TOKEN
from arcraiders.endpoints import STORE_RECONCILE
from arcraiders.endpoints import TENANCY_USER_SYNC
from arcraiders.endpoints import TIMED_OFFERS_TRANSACTIONS

Payload = dict[str, object] | None


class Client:
    def __init__(
        self,
        auth: Auth | str,
        *,
        user_agent: str | None = None,
        telemetry_client_platform: str | None = None,
        telemetry_uuid: str | None = None,
    ) -> None:
        self._auth = TokenAuth(auth) if isinstance(auth, str) else auth
        self._user_agent = user_agent or USER_AGENT
        self._telemetry_client_platform = telemetry_client_platform
        self._telemetry_uuid = telemetry_uuid

    @cache
    def token(self) -> str:
        return self._auth.token()

    @cache
    def manifest(self) -> dict:
        return self._call_endpoint(
            MANIFEST,
            payload={
                "build_id": MANIFEST_BUILD_ID,
                "app_id": MANIFEST_APP_ID,
                "store_deployment_target": MANIFEST_STORE_DEPLOYMENT_TARGET,
                "manifest_id": 0,
            },
        )

    def battlepass_list_battlepasses(self, payload: Payload = None) -> dict:
        return self._call_endpoint(BATTLEPASS_LIST_BATTLEPASSES, payload)

    def bonuses(self, payload: Payload = None) -> dict:
        return self._call_endpoint(BONUSES, payload)

    def codex_entries(self, payload: Payload = None) -> dict:
        return self._call_endpoint(CODEX_ENTRIES, payload)

    def community_event(self, payload: Payload = None) -> dict:
        return self._call_endpoint(COMMUNITY_EVENT, payload)

    def compensations(self, payload: Payload = None) -> dict:
        return self._call_endpoint(COMPENSATIONS, payload)

    def expeditions(self, payload: Payload = None) -> dict:
        return self._call_endpoint(EXPEDITIONS, payload)

    def game_data(self, payload: Payload = None) -> dict:
        return self._call_endpoint(GAME_DATA, payload)

    def game_data_store(self, payload: Payload = None) -> dict:
        return self._call_endpoint(GAME_DATA_STORE, payload)

    def game_settings(self, payload: Payload = None) -> dict:
        return self._call_endpoint(GAME_SETTINGS, payload)

    def get_persistent_player_keys(self, payload: Payload = None) -> dict:
        return self._call_endpoint(GET_PERSISTENT_PLAYER_KEYS, payload)

    def heartbeat(self, payload: Payload = None) -> dict:
        return self._call_endpoint(HEARTBEAT, payload)

    def inbox_get_messages(self, payload: Payload = None) -> dict:
        return self._call_endpoint(INBOX_GET_MESSAGES, payload)

    def inventory(self, payload: Payload = None) -> dict:
        return self._call_endpoint(INVENTORY, payload)

    def inventory_mutate(self, payload: Payload = None) -> dict:
        return self._call_endpoint(INVENTORY_MUTATE, payload)

    def league(self, payload: Payload = None) -> dict:
        return self._call_endpoint(LEAGUE, payload)

    def levels_auto_claim(self, payload: Payload = None) -> dict:
        return self._call_endpoint(LEVELS_AUTO_CLAIM, payload)

    def levels_list(self, payload: Payload = None) -> dict:
        return self._call_endpoint(LEVELS_LIST, payload)

    def localizations(self, payload: Payload = None) -> dict:
        return self._call_endpoint(LOCALIZATIONS, payload)

    def mastery_objectives(self, payload: Payload = None) -> dict:
        return self._call_endpoint(MASTERY_OBJECTIVES, payload)

    def notifications(self, payload: Payload = None) -> dict:
        return self._call_endpoint(NOTIFICATIONS, payload)

    def player_activity(self, payload: Payload = None) -> dict:
        return self._call_endpoint(PLAYER_ACTIVITY, payload)

    def profile(self, payload: Payload = None) -> dict:
        return self._call_endpoint(PROFILE, payload)

    def profile_by_thirdparty_userid(self, payload: Payload = None) -> dict:
        return self._call_endpoint(PROFILE_BY_THIRDPARTY_USERID, payload)

    def projects_list(self, payload: Payload = None) -> dict:
        return self._call_endpoint(PROJECTS_LIST, payload)

    def proxy(self, payload: Payload = None) -> dict:
        return self._call_endpoint(PROXY, payload)

    def quilkin(self, payload: Payload = None) -> dict:
        return self._call_endpoint(QUILKIN, payload)

    def quests(self, payload: Payload = None) -> dict:
        return self._call_endpoint(QUESTS, payload)

    def quests_reconcile(self, payload: Payload = None) -> dict:
        return self._call_endpoint(QUESTS_RECONCILE, payload)

    def quests_reroll_cost(self, payload: Payload = None) -> dict:
        return self._call_endpoint(QUESTS_REROLL_COST, payload)

    def raiders(self, payload: Payload = None) -> dict:
        return self._call_endpoint(RAIDERS, payload)

    def rank_list(self, payload: Payload = None) -> dict:
        return self._call_endpoint(RANK_LIST, payload)

    def scenarios(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SCENARIOS, payload)

    def seasonal_rewards(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SEASONAL_REWARDS, payload)

    def set_persistent_player_keys(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SET_PERSISTENT_PLAYER_KEYS, payload)

    def social_blocked_players(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_BLOCKED_PLAYERS, payload)

    def social_friends_get(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_FRIENDS_GET, payload)

    def social_party_get(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_PARTY_GET, payload)

    def social_party_update_party_member_data(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_PARTY_UPDATE_PARTY_MEMBER_DATA, payload)

    def social_presence_get(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_PRESENCE_GET, payload)

    def social_presence_set_rich_presence(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_PRESENCE_SET_RICH_PRESENCE, payload)

    def social_recently_played_with(self, payload: Payload = None) -> dict:
        return self._call_endpoint(SOCIAL_RECENTLY_PLAYED_WITH, payload)

    def stats_player_v2(self, payload: Payload = None) -> dict:
        return self._call_endpoint(STATS_PLAYER_V2, payload)

    def store_get_microsoft_store_access_token(self, payload: Payload = None) -> dict:
        return self._call_endpoint(STORE_GET_MICROSOFT_STORE_ACCESS_TOKEN, payload)

    def store_reconcile(self, payload: Payload = None) -> dict:
        return self._call_endpoint(STORE_RECONCILE, payload)

    def tenancy_user_sync(self, payload: Payload = None) -> dict:
        return self._call_endpoint(TENANCY_USER_SYNC, payload)

    def timed_offers_transactions(self, payload: Payload = None) -> dict:
        return self._call_endpoint(TIMED_OFFERS_TRANSACTIONS, payload)

    def announcements(self, payload: Payload = None) -> dict:
        return self._call_endpoint(ANNOUNCEMENTS, payload)

    def anticheat_restrictions(self, payload: Payload = None) -> dict:
        return self._call_endpoint(ANTICHEAT_RESTRICTIONS, payload)

    def distribution_platform_achievements_get(self, payload: Payload = None) -> dict:
        return self._call_endpoint(DISTRIBUTION_PLATFORM_ACHIEVEMENTS_GET, payload)

    def _call_endpoint(self, endpoint: Endpoint, payload: Payload = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }
        url = f"{API_BASE_URL}{endpoint.path}"
        request_payload = dict(payload or {})

        if endpoint.requires_manifest:
            headers["x-embark-manifest-id"] = str(self.manifest()["id"])
        if self._telemetry_client_platform:
            headers["x-embark-telemetry-client-platform"] = self._telemetry_client_platform
        if self._telemetry_uuid:
            headers["x-embark-telemetry-uuid"] = self._telemetry_uuid

        if endpoint.method == "GET":
            if request_payload:
                url = f"{url}?{parse.urlencode(request_payload)}"
            body = None
        else:
            body = json.dumps(request_payload).encode("utf-8")

        req = request.Request(url=url, data=body, method=endpoint.method, headers=headers)
        try:
            with request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "ARC Raiders API request failed: "
                f"{endpoint.method} {endpoint.path} "
                f"HTTP {exc.code} "
                f"payload={request_payload!r} "
                f"response={body_text}"
            ) from exc
