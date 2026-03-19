from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import UserProfile


@login_required
def profile_view(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'userapp/profile.html', {'profile': profile})
