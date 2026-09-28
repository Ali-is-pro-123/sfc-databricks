from django.urls import path

from . import views

app_name = "restaurants"
urlpatterns = [
    path("", views.location_list, name="list"),
    path("recommendations/", views.recommendation_evidence, name="recommendations"),
    path("scenarios/", views.what_if_scenarios, name="scenarios"),
    path("<int:pk>/", views.location_detail, name="detail"),
]
