{{/*
Expand the name of the chart.
*/}}
{{- define "pxmx-dashboard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncate to 63 chars because some Kubernetes name fields have that limit.
*/}}
{{- define "pxmx-dashboard.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label value (chart name + version).
*/}}
{{- define "pxmx-dashboard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "pxmx-dashboard.labels" -}}
helm.sh/chart: {{ include "pxmx-dashboard.chart" . }}
{{ include "pxmx-dashboard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (used in matchLabels and Service selector — must be stable).
*/}}
{{- define "pxmx-dashboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pxmx-dashboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name of the Secret that holds the GitHub token.
Uses an existing secret when .Values.github.existingSecret is set,
otherwise uses the chart-managed secret.
*/}}
{{- define "pxmx-dashboard.secretName" -}}
{{- if .Values.github.existingSecret }}
{{- .Values.github.existingSecret }}
{{- else }}
{{- include "pxmx-dashboard.fullname" . }}
{{- end }}
{{- end }}

{{/*
Container image reference, preferring .Values.image.tag over appVersion.
*/}}
{{- define "pxmx-dashboard.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}
