from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    requires_manifest: bool = False


# pioneer
BATTLEPASS_LIST_BATTLEPASSES = Endpoint("GET", "/pioneer/battlepass/list-battlepasses")
BONUSES = Endpoint("GET", "/pioneer/bonuses")
CODEX_ENTRIES = Endpoint("GET", "/pioneer/codex/entries/list", requires_manifest=True)
COMMUNITY_EVENT = Endpoint("GET", "/pioneer/community-event")
COMPENSATIONS = Endpoint("GET", "/pioneer/compensations")
EXPEDITIONS = Endpoint("GET", "/pioneer/expeditions")
GAME_DATA = Endpoint("GET", "/pioneer/game-data", requires_manifest=True)
GAME_DATA_STORE = Endpoint("POST", "/pioneer/game-data/store")
INVENTORY = Endpoint("GET", "/pioneer/inventory", requires_manifest=True)
INVENTORY_MUTATE = Endpoint("POST", "/pioneer/inventory/v1/mutate", requires_manifest=True)
LEAGUE = Endpoint("GET", "/pioneer/league")
LEVELS_AUTO_CLAIM = Endpoint("POST", "/pioneer/levels/auto-claim")
LEVELS_LIST = Endpoint("GET", "/pioneer/levels/list")
MASTERY_OBJECTIVES = Endpoint("GET", "/pioneer/mastery/objectives")
PROJECTS_LIST = Endpoint("POST", "/pioneer/projects/list")
QUESTS = Endpoint("GET", "/pioneer/quests")
QUESTS_RECONCILE = Endpoint("POST", "/pioneer/quests/reconcile")
QUESTS_REROLL_COST = Endpoint("GET", "/pioneer/quests/reroll-cost")
RAIDERS = Endpoint("GET", "/pioneer/raiders")
RANK_LIST = Endpoint("POST", "/pioneer/rank/list")
SEASONAL_REWARDS = Endpoint("GET", "/pioneer/seasonal-rewards")
STATS_PLAYER_V2 = Endpoint("POST", "/pioneer/stats/player-v2")
STORE_GET_MICROSOFT_STORE_ACCESS_TOKEN = Endpoint("GET", "/pioneer/store/get-microsoft-store-access-token")
STORE_RECONCILE = Endpoint("POST", "/pioneer/store/reconcile")
TENANCY_USER_SYNC = Endpoint("POST", "/pioneer/tenancy-user/sync")
TIMED_OFFERS_TRANSACTIONS = Endpoint("GET", "/pioneer/timed-offers/transactions")

# shared
ANNOUNCEMENTS = Endpoint("POST", "/shared/announcements")
ANTICHEAT_RESTRICTIONS = Endpoint("POST", "/shared/anticheat/restrictions")
DISTRIBUTION_PLATFORM_ACHIEVEMENTS_GET = Endpoint("POST", "/shared/distribution-platform-achievements/get")
GAME_SETTINGS = Endpoint("GET", "/shared/game-settings")
GET_PERSISTENT_PLAYER_KEYS = Endpoint("POST", "/shared/get-persistent-player-keys")
HEARTBEAT = Endpoint("POST", "/shared/heartbeat")
INBOX_GET_MESSAGES = Endpoint("POST", "/shared/inbox/get-messages")
LOCALIZATIONS = Endpoint("POST", "/shared/localizations")
MANIFEST = Endpoint("POST", "/shared/manifest")
NOTIFICATIONS = Endpoint("POST", "/shared/notifications")
PLAYER_ACTIVITY = Endpoint("POST", "/shared/player/activity")
PROFILE = Endpoint("GET", "/shared/profile")
PROFILE_BY_THIRDPARTY_USERID = Endpoint("POST", "/shared/profile/by-thirdparty-userid")
PROXY = Endpoint("GET", "/shared/proxy")
QUILKIN = Endpoint("GET", "/shared/quilkin")
SCENARIOS = Endpoint("POST", "/shared/scenarios")
SET_PERSISTENT_PLAYER_KEYS = Endpoint("POST", "/shared/set-persistent-player-keys")
SOCIAL_BLOCKED_PLAYERS = Endpoint("GET", "/shared/social/block-players/blocked-players")
SOCIAL_FRIENDS_GET = Endpoint("GET", "/shared/social/friends/get-friends")
SOCIAL_PARTY_GET = Endpoint("GET", "/shared/social/party/get")
SOCIAL_PARTY_UPDATE_PARTY_MEMBER_DATA = Endpoint("POST", "/shared/social/party/v2/update-party-member-data")
SOCIAL_PRESENCE_GET = Endpoint("POST", "/shared/social/presence/get")
SOCIAL_PRESENCE_SET_RICH_PRESENCE = Endpoint("POST", "/shared/social/presence/set-rich-presence")
SOCIAL_RECENTLY_PLAYED_WITH = Endpoint("GET", "/shared/social/recently-played-with")
