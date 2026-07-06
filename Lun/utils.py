from datetime import timedelta
from django.utils import timezone


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
