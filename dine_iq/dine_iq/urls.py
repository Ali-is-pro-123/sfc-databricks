"""
URL configuration for dine_iq project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from apps.restaurants.admin import management_site
from apps.restaurants import views as restaurant_views

urlpatterns = [
    path('data/', restaurant_views.data_management, name='data_management'),
    path('dashboard/', restaurant_views.executive_dashboard, name='executive_dashboard'),
    path('dashboard/menu/', restaurant_views.menu_intelligence_dashboard, name='menu_dashboard'),
    path('dashboard/customers/', restaurant_views.customer_intelligence_dashboard, name='customer_dashboard'),
    path('dashboard/wastage/', restaurant_views.wastage_intelligence_dashboard, name='wastage_dashboard'),
    path('dashboard/forecast/', restaurant_views.forecast_intelligence_dashboard, name='forecast_dashboard'),
    path('dashboard/dual/', restaurant_views.dual_pipeline_dashboard, name='dual_dashboard'),
    path('dashboard/search/', restaurant_views.analytics_search, name='analytics_search'),
    path('reports/', restaurant_views.report_center, name='report_center'),
    path('reports/<slug:slug>/download/', restaurant_views.download_report, name='download_report'),
    path('exports/<slug:dataset>.csv', restaurant_views.download_csv, name='download_csv'),
    path('locations/', include('apps.restaurants.urls')),
    path('management/', management_site.urls),
    path('', include('apps.accounts.urls')),
    path('admin/', admin.site.urls),
]
