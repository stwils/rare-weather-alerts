# Rare Weather Alerts

Alerts a photographer when weather conditions near home are unusually photogenic — where "rare" means a phenomenon's photographic quality is in the top percentile for that location, not merely that the weather is severe or anomalous.

## Language

**Photo Opportunity**:
The reason an alert exists: weather conditions at a place and time that make photographs possible which ordinary conditions do not.
_Avoid_: Event, occurrence

**Phenomenon**:
A photographable weather situation the system knows how to detect and score (e.g. fog, dramatic storm light, extreme sunrise/sunset, lenticular clouds). Each has its own Quality Score model and Lead Time.
_Avoid_: Condition, event type

**Quality Score**:
A phenomenon-specific measure of how good the photographs would be at a given place and time. The thing the system predicts; higher is more photogenic.
_Avoid_: Severity, intensity

**Rarity Threshold**:
The percentile of a Phenomenon's Quality Score above which an Opportunity exists — judged *regionally*, against the distribution of the daily maximum score across all Spots that share the Phenomenon, not per Spot. Rarity is a percentile on quality, not a category of weather.
_Avoid_: Alert level, severity threshold

**Regional Rarity**:
The principle that a Phenomenon's rarity is measured over the whole Travel Radius at once (the daily-max score across its Spots), so "top 2%" means top 2% of *days a photographer experiences*, not top 2% at each of a dozen correlated Spots — which would fire far more often. See ADR 0002.

**Notable**:
The lower tier: a Quality Score in the regional top 2% of days for a Phenomenon. Appears on the Dashboard and in the Digest; does **not** push on its own.

**Exceptional**:
The upper tier: a Quality Score in the regional top 0.5% of days. The only tier that pushes a live Alert (high priority, but does not bypass Do Not Disturb).
_Avoid_: Critical, severe

**Dashboard**:
The published web page showing every active Opportunity and the full board of best-upcoming scores per Spot. The pull surface — a photographer taps into it — as opposed to Alerts and the Digest, which are pushed.

**Digest**:
A single daily push summarizing the day's board (all Notable+ Opportunities). Sent once each morning, and only when the board is non-empty.
_Avoid_: Summary, roundup

**Spot**:
A curated, named real place within the Travel Radius where Quality Scores are computed, tagged with which Phenomena apply there. A Spot is the photographic subject or area the weather is scored at (e.g. "Mt. Hood" for lenticulars); choosing a viewpoint is the photographer's job, not the system's.
_Avoid_: Sample point, grid cell, location, site, viewpoint

**Travel Radius**:
The drive-time boundary (from home base) within which Spots are chosen, and against which Lead Time is judged — an alert is only useful if the Spot is reachable before the Phenomenon ends.
_Avoid_: Coverage area, range

**Lead Time**:
How far in advance a given phenomenon can be predicted with useful confidence. A property of the phenomenon, not of the alert (days for snow, under an hour for aurora).
_Avoid_: Warning time, notice

**Opportunity**:
A contiguous span of above-threshold Quality Scores for one (Spot, Phenomenon) pair — the domain object alerts are about. Detected once, then tracked across forecast refreshes; short below-threshold gaps do not split it.
_Avoid_: Alert (an alert is a notification about an Opportunity, not the thing itself)

**Alert**:
A push about an *Exceptional* Opportunity's lifecycle change: detected, upgraded (crossed into Exceptional), or cancelled (forecast fell apart). At most one per lifecycle change — never per forecast refresh. Alerts for the same Phenomenon with overlapping windows coalesce into a single push, led by the highest-scoring Spot. Notable Opportunities never raise an Alert; they surface on the Dashboard and Digest.
_Avoid_: Notification, message

**Forecast Alert**:
An alert that a Photo Opportunity is *likely* at a future time, sent with enough Lead Time to plan and travel. Carries a probability; false positives are expected.

**Nowcast Alert**:
An alert that a Photo Opportunity is happening *now* or imminently, for phenomena whose Lead Time is too short to forecast (e.g. aurora).
_Avoid_: Real-time alert, live alert
