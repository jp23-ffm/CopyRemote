from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def compute_days_open(tracker, filtered_fields=None):
    # Return days_open for a tracker instance: if filtered_fields is provided and has matching active issues,
    # return the max days_open among those fields (context-sensitive). Otherwise return the global max (oldest_first_seen).

    if not tracker or not tracker.active_issues:
        return ''

    now = timezone.now()

    if filtered_fields:
        relevant = {f: v for f, v in tracker.active_issues.items() if f in filtered_fields}
        if relevant:
            return max(
                (now - parse_datetime(v['first_seen'])).days + 1
                for v in relevant.values()
            )

    if tracker.oldest_first_seen:
        return (now - tracker.oldest_first_seen).days + 1

    return max(
        (now - parse_datetime(v['first_seen'])).days + 1
        for v in tracker.active_issues.values()
    )


def get_trend_data(metric, days=30):
    """
    Retrieve historical trend data for a specific metric.

    Args:
        metric (str): Field name from AnalysisSnapshot model
        days (int or None): Number of days to look back, or None for all-time

    Returns:
        dict: Contains 'dates' (list of date strings) and 'values' (list of integers)
    """
    from .models import AnalysisSnapshot

    snapshots = AnalysisSnapshot.objects.all()

    if days is not None:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        snapshots = snapshots.filter(analysis_date__gte=start_date, analysis_date__lte=end_date)

    snapshots = snapshots.order_by('analysis_date')

    return {
        'dates': [s.analysis_date.strftime('%d %b') for s in snapshots],
        'values': [getattr(s, metric, 0) for s in snapshots]
    }
