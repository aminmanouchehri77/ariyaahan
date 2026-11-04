"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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

from core.views import legacy_route

urlpatterns = [
    path('admin/', admin.site.urls),
    path('account/', include('accounts.urls')),
    path('', include('core.urls')),
    path('', include('catalog.urls')),
    path('', include('inquiries.urls')),
    path('', include('marketplace.urls')),
    path('', include('orders.urls')),
    path('', include('content.urls')),
    path('<path:old_path>', legacy_route, name='legacy_redirect'),
]

handler404 = 'core.views.page_not_found'
handler500 = 'core.views.server_error'
