from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any, Iterable


VALID_LOCATIONS = ("Local", "Remote", "Internal Network")
VALID_OBJECTIVES = (
    "Download Files",
    "Extract Database",
    "Steal Personal Information",
    "Steal Financial Information",
    "Steal Intellectual Property",
    "Steal Emails / Messages",
    "Capture Login Information",
    "Hijack Account",
    "Profile Target",
    "Plant Bug",
    "Create Back Door",
    "Disable Security",
    "Disrupt System",
    "Destroy Data",
    "Encrypt Files",
    "Deface System / Website",
    "Manipulate Data",
    "Financial Theft",
    "Penetration Test",
)


def _clamp_number(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalise_key(value: Any) -> str:
    return " ".join(str(value or "").strip().replace("_", " ").replace("-", " ").casefold().split())


LOCATION_ALIASES = {
    "local": "Local",
    "remote": "Remote",
    "internal": "Internal Network",
    "internal network": "Internal Network",
    "lan": "Internal Network",
}

OBJECTIVE_ALIASES = {_normalise_key(item): item for item in VALID_OBJECTIVES}
OBJECTIVE_ALIASES.update({
    "download": "Download Files",
    "download file": "Download Files",
    "extract files": "Download Files",
    "database": "Extract Database",
    "database extraction": "Extract Database",
    "personal information": "Steal Personal Information",
    "financial information": "Steal Financial Information",
    "intellectual property": "Steal Intellectual Property",
    "steal email": "Steal Emails / Messages",
    "steal emails": "Steal Emails / Messages",
    "emails": "Steal Emails / Messages",
    "capture credentials": "Capture Login Information",
    "capture login": "Capture Login Information",
    "account hijack": "Hijack Account",
    "profile": "Profile Target",
    "surveillance": "Plant Bug",
    "back door": "Create Back Door",
    "backdoor": "Create Back Door",
    "disable defenses": "Disable Security",
    "disable defences": "Disable Security",
    "disrupt": "Disrupt System",
    "crash system": "Disrupt System",
    "wipe system": "Destroy Data",
    "wipe data": "Destroy Data",
    "encrypt": "Encrypt Files",
    "deface": "Deface System / Website",
    "manipulate": "Manipulate Data",
    "plant false information": "Manipulate Data",
    "steal money": "Financial Theft",
    "crypto theft": "Financial Theft",
    "pentest": "Penetration Test",
    "penetration testing": "Penetration Test",
    "security assessment": "Penetration Test",
})


@dataclass(slots=True)
class HackerScenario:
    operation: str = "Untitled Operation"
    target: str = "Unknown Target"
    target_address: str = "Unknown"
    location: str = "Remote"
    objective: str = "Download Files"
    security: int = 50
    success_rate: float = 75.0
    glitch_rate: float = 8.0
    freeze_rate: float = 4.0
    hackback_chance: float = 4.0
    block_attempts: int = 0
    source_path: Any = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any], source_path: Any = None) -> "HackerScenario":
        warnings: list[str] = []
        location_raw = str(data.get("Location", "Remote")).strip()
        location = LOCATION_ALIASES.get(_normalise_key(location_raw), "Remote")
        if _normalise_key(location_raw) not in LOCATION_ALIASES:
            warnings.append(f"Unknown Location '{location_raw}', using Remote")

        objective_raw = str(data.get("Objective", "Download Files")).strip()
        objective = OBJECTIVE_ALIASES.get(_normalise_key(objective_raw), "Download Files")
        if _normalise_key(objective_raw) not in OBJECTIVE_ALIASES:
            warnings.append(f"Unknown Objective '{objective_raw}', using Download Files")

        success = _clamp_number(data.get("SuccessRate"), 0, 100, 75)
        freeze = _clamp_number(data.get("FreezeRate"), 0, 100, 4)
        if success + freeze > 100:
            freeze = max(0.0, 100.0 - success)
            warnings.append("SuccessRate + FreezeRate exceeded 100; FreezeRate was clamped")

        try:
            blocks = int(float(data.get("BlockAttempts", 0)))
        except (TypeError, ValueError):
            blocks = 0
            warnings.append("Invalid BlockAttempts; using 0")
        blocks = max(0, min(20, blocks))

        return cls(
            operation=str(data.get("Operation", "Untitled Operation")).strip() or "Untitled Operation",
            target=str(data.get("Target", "Unknown Target")).strip() or "Unknown Target",
            target_address=str(data.get("TargetAddress", "Unknown")).strip() or "Unknown",
            location=location,
            objective=objective,
            security=int(round(_clamp_number(data.get("Security"), 0, 100, 50))),
            success_rate=success,
            glitch_rate=_clamp_number(data.get("GlitchRate"), 0, 100, 8),
            freeze_rate=freeze,
            hackback_chance=_clamp_number(data.get("HackBackChance"), 0, 100, 4),
            block_attempts=blocks,
            source_path=source_path,
            warnings=warnings,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "Operation": self.operation,
            "Target": self.target,
            "TargetAddress": self.target_address,
            "Location": self.location,
            "Objective": self.objective,
            "Security": self.security,
            "SuccessRate": self.success_rate,
            "GlitchRate": self.glitch_rate,
            "FreezeRate": self.freeze_rate,
            "HackBackChance": self.hackback_chance,
            "BlockAttempts": self.block_attempts,
            "_Path": self.source_path,
        }


@dataclass(slots=True)
class PlanEvent:
    kind: str
    label: str
    log: str
    duration: float
    tool: str = ""
    meter: str = "PROGRESS"
    details: tuple[str, ...] = ()
    start: float = 0.0
    end: float = 0.0


@dataclass(slots=True)
class TimedEffect:
    kind: str
    at: float
    duration: float
    label: str


@dataclass(slots=True)
class OperationPlan:
    scenario: HackerScenario
    events: list[PlanEvent]
    effects: list[TimedEffect]
    outcome: str
    duration: float
    access_at: float
    seed: int

    def event_at(self, elapsed: float) -> tuple[int, PlanEvent, float]:
        if not self.events:
            fallback = PlanEvent("idle", "ANALYSING", "ANALYSING TARGET", 1.0, start=0.0, end=1.0)
            return 0, fallback, 0.0
        point = max(0.0, min(self.duration, elapsed))
        for index, event in enumerate(self.events):
            if point < event.end or index == len(self.events) - 1:
                local = (point - event.start) / max(0.001, event.duration)
                return index, event, max(0.0, min(1.0, local))
        event = self.events[-1]
        return len(self.events) - 1, event, 1.0

    def active_effects(self, elapsed: float) -> list[TimedEffect]:
        return [effect for effect in self.effects if effect.at <= elapsed < effect.at + effect.duration]


@dataclass(frozen=True, slots=True)
class StageTemplate:
    label: str
    log: str
    duration: float
    tool: str = ""
    meter: str = "PROGRESS"
    details: tuple[str, ...] = ()


LOCATION_RECIPES: dict[str, tuple[StageTemplate, ...]] = {
    "Local": (
        StageTemplate("LOCAL CONTEXT", "LOCAL EXECUTION CONTEXT IDENTIFIED", 1.4, "PowerShell", "CONTEXT", ("[host] system profile collected", "[user] active user context identified", "[session] local execution confirmed")),
        StageTemplate("HOST DISCOVERY", "HOST AND PROCESS INVENTORY GENERATED", 1.8, "Sysinternals", "DISCOVERY", ("[system] platform information mapped", "[process] active processes enumerated", "[service] service inventory refreshed")),
        StageTemplate("PRIVILEGE REVIEW", "LOCAL PRIVILEGE BOUNDARIES IDENTIFIED", 1.7, "ACCESS ANALYSER", "PRIVILEGE", ("[identity] current access level checked", "[policy] restricted actions identified", "[storage] protected resources mapped")),
    ),
    "Remote": (
        StageTemplate("TARGET RESOLUTION", "REMOTE TARGET RESOLVED", 1.5, "ROUTE RESOLVER", "RESOLVE", ("[target] address accepted", "[route] remote path candidate identified", "[transport] reachability confirmed")),
        StageTemplate("SERVICE DISCOVERY", "EXPOSED SERVICE SURFACE MAPPED", 2.0, "Nmap", "DISCOVERY", ("[host] remote service profile acquired", "[service] reachable interfaces identified", "[surface] access boundaries mapped")),
        StageTemplate("TRAFFIC ANALYSIS", "REMOTE TRAFFIC PROFILE GENERATED", 1.7, "Wireshark", "ANALYSIS", ("[packet] protocol mix observed", "[session] transport behaviour profiled", "[route] latency pattern stabilised")),
    ),
    "Internal Network": (
        StageTemplate("NETWORK POSITION", "INTERNAL NETWORK POSITION ESTABLISHED", 1.4, "NETWORK MAPPER", "POSITION", ("[lan] local segment identified", "[gateway] internal route observed", "[scope] reachable network range mapped")),
        StageTemplate("NODE DISCOVERY", "INTERNAL NODES DISCOVERED", 2.0, "Nmap", "DISCOVERY", ("[node] active systems enumerated", "[service] internal services profiled", "[target] candidate hosts correlated")),
        StageTemplate("IDENTITY PATHS", "IDENTITY AND ACCESS PATHS MAPPED", 2.1, "BloodHound", "PATH MAP", ("[identity] relationship graph generated", "[access] privilege paths correlated", "[route] target path candidates ranked")),
        StageTemplate("TARGET PATH", "INTERNAL TARGET PATH SELECTED", 1.6, "PsTools", "ROUTE", ("[service] remote management paths assessed", "[segment] reachable path validated", "[target] final hop selected")),
    ),
}


DEFENSE_POOLS: dict[str, tuple[StageTemplate, ...]] = {
    "Local": (
        StageTemplate("APPLICATION CONTROL", "APPLICATION CONTROL POLICY ENCOUNTERED", 1.8, "POLICY ANALYSER", "POLICY", ("[policy] execution restrictions mapped", "[rule] permitted application paths compared", "[control] execution boundary validated")),
        StageTemplate("ENDPOINT PROTECTION", "ENDPOINT PROTECTION LAYER DETECTED", 2.0, "EDR ANALYSER", "EDR", ("[sensor] endpoint telemetry active", "[policy] behavioural controls observed", "[control] endpoint boundary under analysis")),
        StageTemplate("PRIVILEGE BOUNDARY", "PRIVILEGE BOUNDARY ENCOUNTERED", 1.8, "ACCESS ANALYSER", "PRIVILEGE", ("[identity] standard-user boundary confirmed", "[resource] elevated action required", "[policy] privilege gate under analysis")),
        StageTemplate("PROTECTED STORAGE", "PROTECTED STORAGE BOUNDARY DETECTED", 1.8, "STORAGE ANALYSER", "ACCESS", ("[storage] protected resource identified", "[acl] access policy inspected", "[resource] alternate access context evaluated")),
        StageTemplate("IDENTITY POLICY", "IDENTITY POLICY GATE DETECTED", 1.9, "IDENTITY ANALYSER", "IDENTITY", ("[identity] account policy loaded", "[session] trust requirement observed", "[policy] access conditions correlated")),
    ),
    "Remote": (
        StageTemplate("PERIMETER FIREWALL", "PERIMETER FILTERING DETECTED", 2.0, "FIREWALL ANALYSER", "FILTER", ("[filter] ingress policy observed", "[route] permitted service path compared", "[state] connection policy reconstructed")),
        StageTemplate("APPLICATION FILTER", "APPLICATION PERIMETER CONTROL DETECTED", 2.1, "Burp Suite", "APPLICATION", ("[app] request surface mapped", "[filter] application policy observed", "[session] accepted request patterns analysed")),
        StageTemplate("AUTHENTICATION GATE", "AUTHENTICATION GATE ENCOUNTERED", 2.0, "IDENTITY ANALYSER", "AUTH", ("[identity] login policy identified", "[session] authentication requirements mapped", "[policy] trust conditions correlated")),
        StageTemplate("MFA POLICY", "MULTI-FACTOR POLICY DETECTED", 2.0, "IDENTITY ANALYSER", "MFA", ("[identity] additional factor required", "[policy] session assurance level raised", "[trust] alternate session context evaluated")),
        StageTemplate("ENDPOINT EDR", "ENDPOINT DETECTION LAYER IDENTIFIED", 2.2, "EDR ANALYSER", "EDR", ("[sensor] endpoint telemetry active", "[process] behavioural controls observed", "[control] execution boundary under analysis")),
        StageTemplate("NETWORK SEGMENTATION", "NETWORK SEGMENTATION BOUNDARY DETECTED", 2.0, "ROUTE ANALYSER", "SEGMENT", ("[route] direct path restricted", "[segment] trust boundary mapped", "[path] alternate reachable route identified")),
        StageTemplate("APPLICATION CONTROL", "APPLICATION CONTROL POLICY ENCOUNTERED", 1.9, "POLICY ANALYSER", "POLICY", ("[policy] execution restrictions mapped", "[rule] permitted application paths compared", "[control] application boundary validated")),
    ),
    "Internal Network": (
        StageTemplate("SEGMENTATION", "INTERNAL SEGMENTATION BOUNDARY DETECTED", 2.0, "ROUTE ANALYSER", "SEGMENT", ("[vlan] target segment isolated", "[route] allowed paths enumerated", "[path] alternate internal route evaluated")),
        StageTemplate("IDENTITY TRUST", "IDENTITY TRUST BOUNDARY ENCOUNTERED", 2.1, "BloodHound", "IDENTITY", ("[identity] trust relationships mapped", "[group] privilege relationships correlated", "[path] permitted identity path identified")),
        StageTemplate("REMOTE SERVICE AUTH", "REMOTE SERVICE AUTHENTICATION REQUIRED", 1.9, "PsTools", "AUTH", ("[service] remote management boundary detected", "[identity] accepted context evaluated", "[session] service access path validated")),
        StageTemplate("HOST FIREWALL", "TARGET HOST FIREWALL DETECTED", 1.9, "FIREWALL ANALYSER", "FILTER", ("[filter] host ruleset observed", "[service] permitted internal traffic correlated", "[route] target service path validated")),
        StageTemplate("ENDPOINT EDR", "TARGET ENDPOINT PROTECTION DETECTED", 2.1, "EDR ANALYSER", "EDR", ("[sensor] endpoint telemetry active", "[policy] behavioural controls observed", "[control] endpoint boundary under analysis")),
        StageTemplate("PRIVILEGE BOUNDARY", "TARGET PRIVILEGE BOUNDARY ENCOUNTERED", 1.9, "ACCESS ANALYSER", "PRIVILEGE", ("[identity] current context restricted", "[resource] elevated access required", "[policy] privilege path analysed")),
    ),
}


OBJECTIVE_RECIPES: dict[str, tuple[StageTemplate, ...]] = {
    "Download Files": (
        StageTemplate("STORAGE DISCOVERY", "TARGET STORAGE LOCATIONS ENUMERATED", 1.6, "FILE INDEXER", "DISCOVERY", ("[storage] volumes and shares indexed", "[directory] candidate locations identified", "[filter] target file patterns loaded")),
        StageTemplate("FILE SELECTION", "TARGET FILE SET ASSEMBLED", 1.8, "FILE INDEXER", "SELECT", ("[search] matching files located", "[metadata] file set correlated", "[queue] transfer candidates prepared")),
        StageTemplate("ARCHIVE STAGING", "SELECTED FILES STAGED FOR TRANSFER", 2.0, "7-Zip", "STAGING", ("[archive] staging manifest created", "[compress] archive package prepared", "[verify] source set accounted for")),
        StageTemplate("FILE TRANSFER", "FILE TRANSFER CHANNEL ACTIVE", 2.8, "TRANSFER MANAGER", "TRANSFER", ("[transfer] queued objects streaming", "[channel] throughput stable", "[verify] destination acknowledgements received")),
        StageTemplate("TRANSFER VERIFY", "FILE TRANSFER VERIFIED", 1.3, "CHECKSUM VERIFY", "VERIFY", ("[manifest] object count matched", "[checksum] package validation complete", "[result] files acquired")),
    ),
    "Extract Database": (
        StageTemplate("DATABASE DISCOVERY", "DATABASE SERVICE IDENTIFIED", 1.7, "DB ANALYSER", "DISCOVERY", ("[database] platform profile generated", "[schema] repository structure detected", "[session] data service context prepared")),
        StageTemplate("SCHEMA MAP", "DATABASE SCHEMA MAPPED", 1.8, "DB ANALYSER", "SCHEMA", ("[schema] tables enumerated", "[records] row counts estimated", "[relation] candidate datasets correlated")),
        StageTemplate("RECORD SELECTION", "TARGET RECORD SET IDENTIFIED", 1.7, "QUERY ANALYSER", "SELECT", ("[filter] relevant records identified", "[dataset] export set assembled", "[verify] selection scope confirmed")),
        StageTemplate("DATABASE EXPORT", "DATABASE EXPORT ACTIVE", 2.6, "EXPORT MANAGER", "EXPORT", ("[export] records serialised", "[package] dataset staged", "[transfer] export stream active")),
        StageTemplate("EXPORT VERIFY", "DATABASE EXTRACTION VERIFIED", 1.3, "CHECKSUM VERIFY", "VERIFY", ("[records] export count matched", "[integrity] dataset validation complete", "[result] database extracted")),
    ),
    "Steal Personal Information": (
        StageTemplate("IDENTITY DATA SEARCH", "PERSONAL DATA SOURCES IDENTIFIED", 1.8, "DATA CLASSIFIER", "SEARCH", ("[identity] personal-record patterns loaded", "[source] matching repositories located", "[record] candidate identities correlated")),
        StageTemplate("PROFILE CORRELATION", "PERSONAL RECORDS CORRELATED", 2.0, "PROFILE BUILDER", "CORRELATE", ("[record] duplicate identities merged", "[profile] attributes associated", "[dataset] profile set assembled")),
        StageTemplate("RECORD STAGING", "PERSONAL RECORD SET STAGED", 1.8, "ARCHIVE MANAGER", "STAGING", ("[dataset] selected profiles packaged", "[manifest] record index created", "[verify] staging set complete")),
        StageTemplate("DATA TRANSFER", "PERSONAL DATA TRANSFER ACTIVE", 2.5, "TRANSFER MANAGER", "TRANSFER", ("[transfer] record package streaming", "[channel] acknowledgements received", "[verify] destination count rising")),
    ),
    "Steal Financial Information": (
        StageTemplate("FINANCIAL DATA SEARCH", "FINANCIAL DATA SOURCES IDENTIFIED", 1.9, "DATA CLASSIFIER", "SEARCH", ("[record] account and transaction patterns loaded", "[source] financial repositories located", "[dataset] matching records indexed")),
        StageTemplate("ACCOUNT CORRELATION", "FINANCIAL RECORDS CORRELATED", 1.9, "RECORD ANALYSER", "CORRELATE", ("[account] related records grouped", "[transaction] history references mapped", "[dataset] export set assembled")),
        StageTemplate("FINANCIAL EXPORT", "FINANCIAL RECORD EXPORT ACTIVE", 2.6, "EXPORT MANAGER", "EXPORT", ("[export] selected records serialised", "[package] financial dataset staged", "[transfer] export stream active")),
        StageTemplate("EXPORT VERIFY", "FINANCIAL INFORMATION ACQUIRED", 1.4, "CHECKSUM VERIFY", "VERIFY", ("[records] export count matched", "[integrity] dataset verified", "[result] financial records acquired")),
    ),
    "Steal Intellectual Property": (
        StageTemplate("PROJECT DISCOVERY", "PROJECT AND REPOSITORY SOURCES IDENTIFIED", 1.8, "Git", "DISCOVERY", ("[repo] project sources enumerated", "[branch] active development paths mapped", "[artifact] confidential material indexed")),
        StageTemplate("IP SELECTION", "INTELLECTUAL PROPERTY SET IDENTIFIED", 1.8, "REPOSITORY ANALYSER", "SELECT", ("[source] code and research candidates ranked", "[document] design material correlated", "[queue] selected artifacts prepared")),
        StageTemplate("REPOSITORY STAGING", "PROJECT MATERIAL STAGED", 2.0, "7-Zip", "STAGING", ("[repo] selected project content packaged", "[manifest] source index generated", "[verify] artifact set accounted for")),
        StageTemplate("IP TRANSFER", "INTELLECTUAL PROPERTY TRANSFER ACTIVE", 2.8, "TRANSFER MANAGER", "TRANSFER", ("[transfer] project package streaming", "[channel] throughput stable", "[verify] destination acknowledgements received")),
    ),
    "Steal Emails / Messages": (
        StageTemplate("MAIL DISCOVERY", "MAIL AND MESSAGE STORES IDENTIFIED", 1.8, "MAIL ANALYSER", "DISCOVERY", ("[mailbox] folders enumerated", "[channel] message sources indexed", "[attachment] related files identified")),
        StageTemplate("MESSAGE SEARCH", "TARGET CONVERSATIONS IDENTIFIED", 1.9, "MESSAGE INDEXER", "SEARCH", ("[search] people and keyword filters applied", "[thread] matching conversations correlated", "[attachment] related items queued")),
        StageTemplate("MESSAGE EXPORT", "MAILBOX EXPORT ACTIVE", 2.6, "EXPORT MANAGER", "EXPORT", ("[export] messages serialised", "[attachment] related files packaged", "[transfer] mailbox stream active")),
        StageTemplate("EXPORT VERIFY", "MESSAGES AND ATTACHMENTS ACQUIRED", 1.3, "CHECKSUM VERIFY", "VERIFY", ("[message] export count matched", "[attachment] manifest validated", "[result] communications acquired")),
    ),
    "Capture Login Information": (
        StageTemplate("AUTH SOURCE DISCOVERY", "AUTHENTICATION SOURCES IDENTIFIED", 1.8, "CREDENTIAL ANALYSER", "DISCOVERY", ("[identity] login sources enumerated", "[session] active authentication contexts observed", "[store] candidate credential material located")),
        StageTemplate("CREDENTIAL COLLECTION", "CREDENTIAL MATERIAL CAPTURE ACTIVE", 2.2, "Mimikatz", "CAPTURE", ("[credential] candidate material detected", "[identity] account context correlated", "[session] authentication artifacts staged")),
        StageTemplate("CREDENTIAL VALIDATION", "CAPTURED LOGIN MATERIAL VALIDATED", 1.8, "IDENTITY ANALYSER", "VALIDATE", ("[account] identity matched", "[auth] candidate material verified", "[result] login information captured")),
    ),
    "Hijack Account": (
        StageTemplate("ACCOUNT DISCOVERY", "TARGET ACCOUNT CONTEXT IDENTIFIED", 1.7, "IDENTITY ANALYSER", "DISCOVERY", ("[account] active identities enumerated", "[session] authenticated contexts observed", "[target] account selected")),
        StageTemplate("SESSION ACQUISITION", "TARGET SESSION CONTEXT ACQUIRED", 2.2, "SESSION ANALYSER", "SESSION", ("[session] authentication context reconstructed", "[identity] target security context prepared", "[trust] session conditions correlated")),
        StageTemplate("ACCOUNT CONTROL", "TARGET ACCOUNT SESSION ESTABLISHED", 1.9, "SESSION MANAGER", "CONTROL", ("[account] target identity active", "[resource] accessible services verified", "[result] account controlled")),
    ),
    "Profile Target": (
        StageTemplate("PUBLIC SOURCE SEARCH", "PUBLIC TARGET SOURCES COLLECTED", 1.9, "OSINT ANALYSER", "SEARCH", ("[public] web references collected", "[identity] names and roles correlated", "[technical] domains and systems indexed")),
        StageTemplate("IDENTITY CORRELATION", "TARGET IDENTITIES CORRELATED", 2.0, "PROFILE BUILDER", "CORRELATE", ("[identity] aliases merged", "[contact] relationships linked", "[confidence] profile confidence increasing")),
        StageTemplate("TECHNICAL PROFILE", "TARGET TECHNICAL FOOTPRINT MAPPED", 1.9, "PROFILE BUILDER", "PROFILE", ("[system] known services associated", "[domain] technical references linked", "[network] observed target context added")),
        StageTemplate("DOSSIER BUILD", "TARGET DOSSIER GENERATED", 1.8, "DOSSIER BUILDER", "BUILD", ("[profile] identity summary compiled", "[relationship] graph finalised", "[result] profile complete")),
    ),
    "Plant Bug": (
        StageTemplate("SURVEILLANCE DISCOVERY", "SURVEILLANCE CHANNELS IDENTIFIED", 1.8, "CHANNEL ANALYSER", "DISCOVERY", ("[screen] capture channel assessed", "[input] activity channel assessed", "[audio] available capture paths checked")),
        StageTemplate("MONITOR DEPLOYMENT", "SURVEILLANCE MONITOR CONFIGURED", 2.3, "Cobalt Strike", "DEPLOY", ("[monitor] selected channels configured", "[schedule] recurring collection prepared", "[channel] return path established")),
        StageTemplate("CAPTURE TEST", "SURVEILLANCE CAPTURE TEST ACTIVE", 1.8, "MONITOR CONSOLE", "TEST", ("[screen] sample capture received", "[input] activity sample received", "[network] collection channel verified")),
        StageTemplate("BUG VERIFY", "SURVEILLANCE CHANNEL VERIFIED", 1.4, "MONITOR CONSOLE", "VERIFY", ("[monitor] recurring collection active", "[channel] telemetry stable", "[result] surveillance active")),
    ),
    "Create Back Door": (
        StageTemplate("PERSISTENCE ANALYSIS", "PERSISTENCE OPPORTUNITIES IDENTIFIED", 1.9, "PERSISTENCE ANALYSER", "ANALYSIS", ("[account] persistent access options assessed", "[startup] recurring execution paths checked", "[remote] management channels evaluated")),
        StageTemplate("BACK DOOR DEPLOYMENT", "PERSISTENT ACCESS CHANNEL CONFIGURED", 2.4, "REMOTE ACCESS MANAGER", "DEPLOY", ("[persistence] selected method configured", "[channel] return path registered", "[policy] reconnect conditions prepared")),
        StageTemplate("RECONNECT TEST", "PERSISTENT ACCESS RECONNECT TEST ACTIVE", 2.0, "SESSION MANAGER", "RECONNECT", ("[session] original context released", "[channel] return path reopened", "[identity] access context restored")),
        StageTemplate("PERSISTENCE VERIFY", "BACK DOOR VERIFIED", 1.4, "SESSION MANAGER", "VERIFY", ("[reconnect] repeated session accepted", "[persistence] access survived boundary test", "[result] back door verified")),
    ),
    "Disable Security": (
        StageTemplate("DEFENSE DISCOVERY", "DEFENSIVE COMPONENTS IDENTIFIED", 1.8, "SECURITY ANALYSER", "DISCOVERY", ("[edr] endpoint controls enumerated", "[firewall] network controls mapped", "[audit] monitoring channels identified")),
        StageTemplate("CONTROL SUPPRESSION", "DEFENSIVE CONTROLS DEGRADED", 2.5, "CONTROL MANAGER", "SUPPRESS", ("[control] selected defense state changing", "[telemetry] monitoring coverage falling", "[policy] security components degraded")),
        StageTemplate("DEFENSE VERIFY", "SECURITY SUPPRESSION VERIFIED", 1.6, "SECURITY ANALYSER", "VERIFY", ("[edr] defensive visibility reduced", "[firewall] selected restrictions inactive", "[result] security capability degraded")),
    ),
    "Disrupt System": (
        StageTemplate("SERVICE DISCOVERY", "CRITICAL SERVICES IDENTIFIED", 1.8, "SERVICE ANALYSER", "DISCOVERY", ("[service] critical components enumerated", "[dependency] service relationships mapped", "[impact] availability dependencies ranked")),
        StageTemplate("SERVICE DISRUPTION", "TARGET SERVICES ENTERING FAILURE STATE", 2.6, "SERVICE CONTROL", "DISRUPT", ("[service] availability dropping", "[dependency] dependent components degrading", "[health] target response deteriorating")),
        StageTemplate("OUTAGE VERIFY", "TARGET AVAILABILITY FAILURE VERIFIED", 1.6, "HEALTH MONITOR", "VERIFY", ("[health] service checks failing", "[response] target availability lost", "[result] system disrupted")),
    ),
    "Destroy Data": (
        StageTemplate("DATA SCOPE", "DESTRUCTIVE DATA SCOPE IDENTIFIED", 1.7, "STORAGE ANALYSER", "SCOPE", ("[storage] target data locations mapped", "[scope] destructive set assembled", "[permission] write access confirmed")),
        StageTemplate("DATA DESTRUCTION", "DESTRUCTIVE DATA OPERATION ACTIVE", 2.8, "DESTRUCTION MONITOR", "DESTROY", ("[object] selected data being removed", "[storage] object count falling", "[recovery] recovery state deteriorating")),
        StageTemplate("DESTRUCTION VERIFY", "TARGET DATA DESTRUCTION VERIFIED", 1.6, "STORAGE ANALYSER", "VERIFY", ("[object] target set no longer available", "[integrity] destructive scope confirmed", "[result] data destroyed")),
    ),
    "Encrypt Files": (
        StageTemplate("WRITABLE DATA DISCOVERY", "WRITABLE FILE SET IDENTIFIED", 1.8, "FILE INDEXER", "DISCOVERY", ("[storage] writable locations enumerated", "[file] candidate objects counted", "[scope] encryption set prepared")),
        StageTemplate("FILE ENCRYPTION", "FILE ENCRYPTION SIMULATION ACTIVE", 3.0, "ENCRYPTION MONITOR", "ENCRYPT", ("[file] locked-object count increasing", "[skip] inaccessible objects recorded", "[state] normal access declining")),
        StageTemplate("LOCK VERIFY", "FILE ACCESS DENIAL VERIFIED", 1.5, "FILE VALIDATOR", "VERIFY", ("[file] selected objects inaccessible", "[manifest] locked set verified", "[result] data access denied")),
    ),
    "Deface System / Website": (
        StageTemplate("VISIBLE CONTENT", "VISIBLE TARGET CONTENT IDENTIFIED", 1.6, "CONTENT ANALYSER", "DISCOVERY", ("[page] presentation resources mapped", "[asset] visible content identified", "[publish] update path checked")),
        StageTemplate("CONTENT MODIFICATION", "VISIBLE TARGET CONTENT MODIFIED", 2.2, "CONTENT EDITOR", "MODIFY", ("[asset] replacement content staged", "[publish] presentation state updated", "[cache] visible content refreshed")),
        StageTemplate("DEFACEMENT VERIFY", "VISIBLE MODIFICATION VERIFIED", 1.5, "CONTENT VALIDATOR", "VERIFY", ("[view] modified presentation loaded", "[publish] target reflects new content", "[result] defacement live")),
    ),
    "Manipulate Data": (
        StageTemplate("DATASET DISCOVERY", "TARGET DATASET IDENTIFIED", 1.7, "DATA ANALYSER", "DISCOVERY", ("[dataset] relevant records located", "[schema] relationships mapped", "[record] modification candidates selected")),
        StageTemplate("RECORD MODIFICATION", "TARGET RECORDS MODIFIED", 2.4, "RECORD EDITOR", "MODIFY", ("[record] selected values changing", "[relation] dependent records recalculated", "[state] modified dataset committed")),
        StageTemplate("CHANGE VERIFY", "DATA MANIPULATION VERIFIED", 1.5, "DATA VALIDATOR", "VERIFY", ("[query] modified records reloaded", "[integrity] requested changes present", "[result] data altered")),
    ),
    "Financial Theft": (
        StageTemplate("ASSET DISCOVERY", "FINANCIAL ASSETS IDENTIFIED", 1.8, "ACCOUNT ANALYSER", "DISCOVERY", ("[account] available assets enumerated", "[balance] value state observed", "[transfer] destination context prepared")),
        StageTemplate("TRANSACTION BUILD", "SIMULATED TRANSACTION PREPARED", 2.0, "TRANSACTION CONSOLE", "PREPARE", ("[source] transfer source selected", "[destination] target route assigned", "[ledger] pending transaction created")),
        StageTemplate("VALUE TRANSFER", "SIMULATED VALUE TRANSFER PROCESSING", 2.8, "TRANSACTION CONSOLE", "TRANSFER", ("[transaction] processing state active", "[ledger] source balance changing", "[confirmation] settlement state pending")),
        StageTemplate("TRANSFER CONFIRM", "SIMULATED FINANCIAL TRANSFER CONFIRMED", 1.5, "LEDGER MONITOR", "VERIFY", ("[transaction] confirmation received", "[ledger] final state reflected", "[result] funds transferred")),
    ),
    "Penetration Test": (
        StageTemplate("SCOPE VERIFICATION", "AUTHORISED TEST SCOPE VERIFIED", 1.5, "ASSESSMENT CONSOLE", "SCOPE", ("[scope] authorised targets loaded", "[rules] test boundaries confirmed", "[logging] evidence collection enabled")),
        StageTemplate("SECURITY MAPPING", "SECURITY CONTROL MAP GENERATED", 1.9, "Nmap", "MAPPING", ("[service] attack surface documented", "[control] security layers identified", "[evidence] observations recorded")),
        StageTemplate("VULNERABILITY REVIEW", "POTENTIAL SECURITY FINDINGS IDENTIFIED", 2.1, "Burp Suite", "ASSESS", ("[finding] candidate weaknesses classified", "[risk] severity estimates assigned", "[evidence] validation targets queued")),
        StageTemplate("CONTROLLED VALIDATION", "CONTROLLED FINDING VALIDATION ACTIVE", 2.3, "Metasploit", "VALIDATE", ("[test] selected findings validated", "[impact] access boundaries demonstrated", "[evidence] proof points captured")),
        StageTemplate("CLEANUP", "ASSESSMENT TEST STATE CLEANED", 1.6, "ASSESSMENT CONSOLE", "CLEANUP", ("[session] test access released", "[artifact] temporary test state cleared", "[evidence] retained observations finalised")),
        StageTemplate("REPORT", "PENETRATION TEST REPORT GENERATED", 1.8, "REPORT BUILDER", "REPORT", ("[finding] severity totals compiled", "[remediation] recommendation sections prepared", "[result] assessment complete")),
    ),
}


BLOCK_TEXT = {
    "Local": ("PROCESS BLOCKED", "POLICY CHANGE INTERRUPTED PROCESS", "LOCAL SESSION RESTRICTED"),
    "Remote": ("CONNECTION BLOCKED", "REMOTE SESSION INVALIDATED", "ACCESS PATH REJECTED"),
    "Internal Network": ("INTERNAL PATH BLOCKED", "REMOTE SERVICE SESSION REVOKED", "SEGMENT POLICY CHANGED"),
}


class HackerSimulator:
    def __init__(self, seed: int | None = None):
        self.seed = seed

    @staticmethod
    def _clone(template: StageTemplate, kind: str, security: int = 0, rng: random.Random | None = None) -> PlanEvent:
        random_source = rng or random
        scale = 1.0 + max(0, security) / 260.0
        jitter = random_source.uniform(0.88, 1.12)
        return PlanEvent(
            kind=kind,
            label=template.label,
            log=template.log,
            duration=max(0.55, template.duration * scale * jitter),
            tool=template.tool,
            meter=template.meter,
            details=template.details,
        )

    @staticmethod
    def _security_layer_count(security: int, rng: random.Random) -> int:
        if security <= 0:
            return 0
        baseline = security / 14.5
        count = int(round(baseline + rng.uniform(-0.9, 0.9)))
        if security < 20:
            return max(0, min(2, count))
        if security < 40:
            return max(1, min(3, count))
        if security < 60:
            return max(2, min(5, count))
        if security < 80:
            return max(4, min(7, count))
        if security < 95:
            return max(5, min(8, count))
        return max(7, min(9, count + 1))

    @staticmethod
    def _method_failures(security: int, rng: random.Random) -> int:
        failures = 0
        if rng.random() < security / 130.0:
            failures += 1
        if security >= 60 and rng.random() < (security - 45) / 130.0:
            failures += 1
        if security >= 85 and rng.random() < (security - 70) / 120.0:
            failures += 1
        return min(3, failures)

    @staticmethod
    def _failure_event(label: str, security: int, rng: random.Random) -> PlanEvent:
        phrases = (
            "METHOD REJECTED / REASSESSING",
            "ACCESS VECTOR FAILED / SELECTING ALTERNATE",
            "POLICY RESPONSE REJECTED / RECALCULATING",
            "SESSION PATH DENIED / ALTERNATE METHOD REQUIRED",
        )
        details = (
            "[method] current approach rejected",
            "[analysis] response conditions changed",
            "[planner] alternate method selected",
        )
        return PlanEvent(
            "method_fail",
            "METHOD REJECTED",
            rng.choice(phrases),
            rng.uniform(0.7, 1.25) * (1.0 + security / 240.0),
            "METHOD PLANNER",
            "REASSESS",
            details,
        )

    def _build_security_events(self, scenario: HackerScenario, rng: random.Random) -> list[PlanEvent]:
        pool = list(DEFENSE_POOLS[scenario.location])
        rng.shuffle(pool)
        layer_count = self._security_layer_count(scenario.security, rng)
        chosen: list[StageTemplate] = []
        while len(chosen) < layer_count and pool:
            chosen.append(pool[len(chosen) % len(pool)])
            if len(chosen) == len(pool) and len(chosen) < layer_count:
                pool.extend(rng.sample(list(DEFENSE_POOLS[scenario.location]), len(DEFENSE_POOLS[scenario.location])))
        events: list[PlanEvent] = []
        for defense in chosen[:layer_count]:
            for _ in range(self._method_failures(scenario.security, rng)):
                events.append(self._failure_event(defense.label, scenario.security, rng))
            events.append(self._clone(defense, "security", scenario.security, rng))
        return events

    @staticmethod
    def _resource_gate(scenario: HackerScenario, rng: random.Random) -> list[PlanEvent]:
        if scenario.security < 45 or rng.random() > scenario.security / 120.0:
            return []
        possible = list(DEFENSE_POOLS[scenario.location])
        template = rng.choice(possible)
        return [PlanEvent(
            "resource_security",
            f"RESOURCE {template.label}",
            "ADDITIONAL RESOURCE SECURITY GATE ENCOUNTERED",
            max(0.8, template.duration * (0.85 + scenario.security / 220.0)),
            template.tool,
            template.meter,
            template.details,
        )]

    @staticmethod
    def _insert_blocks(events: list[PlanEvent], scenario: HackerScenario, rng: random.Random) -> list[PlanEvent]:
        if scenario.block_attempts <= 0 or len(events) < 3:
            return events
        result = list(events)
        eligible = list(range(1, max(2, len(result) - 1)))
        attempts = scenario.block_attempts
        positions = sorted(rng.choices(eligible, k=attempts), reverse=True)
        severity = scenario.security / 100.0
        for position in positions:
            text = rng.choice(BLOCK_TEXT[scenario.location])
            if severity >= 0.8 and rng.random() < 0.4:
                recovery = "REBUILDING ACCESS PATH"
            elif severity >= 0.5 and rng.random() < 0.5:
                recovery = "RESTARTING CURRENT PROCESS"
            else:
                recovery = "RETRYING INTERRUPTED PROCESS"
            block = PlanEvent(
                "block",
                "ACTIVE BLOCK",
                f"{text} / {recovery}",
                rng.uniform(1.0, 1.8) * (1.0 + severity * 0.5),
                "RESPONSE MONITOR",
                "RECOVERY",
                ("[defender] active interference detected", f"[response] {text.lower()}", f"[recovery] {recovery.lower()}"),
            )
            result.insert(min(position + 1, len(result)), block)
        return result

    @staticmethod
    def _decide_outcome(scenario: HackerScenario, rng: random.Random) -> str:
        roll = rng.random() * 100.0
        if roll < scenario.freeze_rate:
            return "FREEZE"
        if roll < scenario.freeze_rate + scenario.success_rate:
            return "SUCCESS"
        return "FAILURE"

    @staticmethod
    def _pace_scale(settings: dict[str, Any] | None) -> float:
        if not settings:
            return 1.0
        try:
            pace = float(settings.get("Pace", 100.0))
        except (TypeError, ValueError):
            pace = 100.0
        if "Pace" not in settings and "OperationTime" in settings:
            try:
                pace = float(settings.get("OperationTime", 24.0)) / 24.0 * 100.0
            except (TypeError, ValueError):
                pace = 100.0
        return max(0.45, min(2.5, 100.0 / max(40.0, min(220.0, pace))))

    def build_plan(self, scenario: HackerScenario, settings: dict[str, Any] | None = None, seed: int | None = None) -> OperationPlan:
        actual_seed = seed if seed is not None else (self.seed if self.seed is not None else random.randrange(1, 2**31 - 1))
        rng = random.Random(actual_seed)
        outcome = self._decide_outcome(scenario, rng)
        events: list[PlanEvent] = []

        for stage in LOCATION_RECIPES[scenario.location]:
            events.append(self._clone(stage, "location", scenario.security // 3, rng))

        security_events = self._build_security_events(scenario, rng)
        events.extend(security_events)

        access_event = PlanEvent(
            "access",
            "ACCESS ESTABLISHED",
            "TARGET ACCESS ESTABLISHED",
            rng.uniform(1.0, 1.6),
            "SESSION MANAGER",
            "ACCESS",
            ("[session] target context established", "[identity] active access level confirmed", "[planner] objective phase authorised"),
        )
        events.append(access_event)
        access_index = len(events) - 1

        objective_templates = OBJECTIVE_RECIPES.get(scenario.objective, OBJECTIVE_RECIPES["Download Files"])
        objective_events = [self._clone(stage, "objective", scenario.security // 4, rng) for stage in objective_templates]
        if objective_events:
            gate = self._resource_gate(scenario, rng)
            if gate:
                insertion = min(len(objective_events), max(1, len(objective_events) // 2))
                objective_events[insertion:insertion] = gate
        events.extend(objective_events)

        access_index = next((index for index, event in enumerate(events) if event.kind == "access"), max(0, len(events) // 2))

        if outcome == "FAILURE" and len(events) > access_index + 1:
            low = max(2, int(len(events) * 0.48))
            high = max(low, int(len(events) * 0.90))
            cutoff = rng.randint(low, min(high, len(events) - 1))
            events = events[:cutoff]
            events.append(PlanEvent(
                "failure",
                "OPERATION FAILURE",
                "AVAILABLE METHODS EXHAUSTED / OPERATION ABORTED",
                rng.uniform(1.8, 2.8),
                "FAILURE ANALYSER",
                "FAILURE",
                ("[planner] remaining paths rejected", "[session] viable access state lost", "[result] operation failed"),
            ))
        elif outcome == "FREEZE" and len(events) > 3:
            low = max(2, int(len(events) * 0.32))
            high = max(low, int(len(events) * 0.84))
            cutoff = rng.randint(low, min(high, len(events) - 1))
            events = events[:cutoff]
            events.append(PlanEvent(
                "freeze",
                "PROCESS FROZEN",
                "PROCESS UNRESPONSIVE / RECOVERY FAILED",
                rng.uniform(2.4, 3.8),
                "SESSION MONITOR",
                "RESPONSE",
                ("[process] response delay detected", "[session] process no longer responding", "[recovery] recovery attempt failed"),
            ))

        events = self._insert_blocks(events, scenario, rng)

        pace = self._pace_scale(settings)
        cursor = 0.0
        for event in events:
            event.duration *= pace
            event.start = cursor
            event.end = cursor + event.duration
            cursor = event.end
        duration = max(1.0, cursor)

        access_event_found = next((event for event in events if event.kind == "access"), None)
        access_at = access_event_found.start if access_event_found else duration * 0.70

        effects: list[TimedEffect] = []
        if scenario.glitch_rate > 0 and rng.random() * 100.0 < scenario.glitch_rate:
            at = rng.uniform(duration * 0.15, max(duration * 0.16, duration * 0.90))
            effects.append(TimedEffect("glitch", at, rng.uniform(0.22, 0.55), "VISUAL GLITCH"))
        if scenario.hackback_chance > 0 and rng.random() * 100.0 < scenario.hackback_chance:
            start_floor = max(duration * 0.35, min(duration * 0.65, access_at * 0.75))
            start_ceiling = max(start_floor + 0.2, duration * 0.82)
            at = rng.uniform(start_floor, start_ceiling)
            effects.append(TimedEffect("hackback", at, rng.uniform(3.5, 5.8) * pace, "COUNTER-INTRUSION ACTIVE"))
        effects.sort(key=lambda item: item.at)

        return OperationPlan(scenario, events, effects, outcome, duration, access_at, actual_seed)


def parse_scenario_text(text: str, source_path: Any = None) -> HackerScenario:
    data: dict[str, str] = {}
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            data[key] = value
    return HackerScenario.from_mapping(data, source_path)
