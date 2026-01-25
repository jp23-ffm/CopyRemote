from datetime import timedelta
from django.utils import timezone


def get_trend_data(metric, days=30):
    """
    Retrieve historical trend data for a specific metric.
    
    Args:
        metric (str): Field name from AnalysisSnapshot model
        days (int): Number of days to look back
    
    Returns:
        dict: Contains 'dates' (list of date strings) and 'values' (list of integers)
    """
    from .models import AnalysisSnapshot
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    snapshots = AnalysisSnapshot.objects.filter(
        analysis_date__gte=start_date,
        analysis_date__lte=end_date
    ).order_by('analysis_date')
    
    return {
        'dates': [s.analysis_date.strftime('%d %b') for s in snapshots],
        'values': [getattr(s, metric, 0) for s in snapshots]
    }
