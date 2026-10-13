{{- define "ace.webLabels" -}}
app.kubernetes.io/name: web
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Labels for one component; call with (list . "name"). */}}
{{- define "ace.labels" -}}
app.kubernetes.io/name: {{ index . 1 }}
app.kubernetes.io/instance: {{ (index . 0).Release.Name }}
{{- end -}}

{{/* The app Secret (decisions D1 = A): generated once, kept on every upgrade. */}}
{{- define "ace.secretName" -}}
{{ .Release.Name }}-app
{{- end -}}

{{/* A Service's in-cluster DNS name; call with (list . "service"). */}}
{{- define "ace.host" -}}
{{ index . 1 }}.{{ (index . 0).Release.Namespace }}.svc.cluster.local
{{- end -}}

{{/* An env entry read from the app Secret; call with (list . "ENV_NAME" "secret-key"). */}}
{{- define "ace.secretEnv" -}}
- name: {{ index . 1 }}
  valueFrom:
    secretKeyRef:
      name: {{ include "ace.secretName" (index . 0) }}
      key: {{ index . 2 }}
{{- end -}}

{{/* The Python image's container command for a module. With python.reload (make dev),
a file watcher restarts the process when Tilt syncs a saved .py file into the pod. */}}
{{- define "ace.pythonCommand" -}}
{{- $root := index . 0 -}}
{{- $module := index . 1 -}}
{{- if $root.Values.python.reload }}
- watchfiles
- --filter
- python
- --target-type
- command
- {{ printf "python -m %s" $module | quote }}
- /app/apps
- /app/services
{{- else }}
- python
- -m
- {{ $module }}
{{- end }}
{{- end -}}

{{- define "ace.pythonImage" -}}
image: "{{ .Values.python.image.repository }}:{{ .Values.python.image.tag }}"
imagePullPolicy: {{ .Values.python.image.pullPolicy }}
{{- end -}}

{{/* Settings shared by the API and the worker (apps/engine/ace_engine/env.py). */}}
{{- define "ace.engineEnv" -}}
- name: ACE_DEPTH
  value: {{ .Values.depth | quote }}
- name: ACE_DATABASE_URL
  value: {{ printf "postgresql+psycopg://%s@%s:%v/%s" .Values.postgres.user (include "ace.host" (list . .Values.postgres.serviceName)) .Values.postgres.port .Values.postgres.database | quote }}
{{ include "ace.secretEnv" (list . "ACE_DATABASE_PASSWORD" "postgres-password") }}
- name: ACE_TEMPORAL_ADDRESS
  value: {{ printf "%s:%v" (include "ace.host" (list . .Values.temporal.serviceName)) .Values.temporal.port | quote }}
- name: ACE_TEMPORAL_NAMESPACE
  value: {{ .Values.temporal.namespace | quote }}
- name: ACE_AGENT_URL
  value: {{ .Values.worker.agentUrl | quote }}
- name: ACE_AGENT_TIMEOUT_SECONDS
  value: {{ .Values.worker.agentTimeoutSeconds | quote }}
- name: ACE_KAGENT_API_URL
  value: {{ .Values.worker.kagentApiUrl | quote }}
- name: ACE_MARKETO_URL
  value: {{ printf "http://%s:%v" (include "ace.host" (list . .Values.marketo.serviceName)) .Values.marketo.port | quote }}
- name: ACE_CMS_URL
  value: {{ printf "http://%s:%v" (include "ace.host" (list . .Values.cms.serviceName)) .Values.cms.port | quote }}
- name: ACE_S3_URL
  value: {{ printf "http://%s:%v" (include "ace.host" (list . .Values.s3.serviceName)) .Values.s3.port | quote }}
- name: ACE_S3_BUCKET
  value: {{ .Values.s3.bucket | quote }}
- name: ACE_MARKETO_CLIENT_ID
  value: {{ .Values.marketo.clientId | quote }}
{{ include "ace.secretEnv" (list . "ACE_MARKETO_CLIENT_SECRET" "marketo-client-secret") }}
{{ include "ace.secretEnv" (list . "ACE_MARKETO_WEBHOOK_SECRET" "marketo-webhook-secret") }}
{{- end -}}

{{/* OpenTelemetry settings for one service; call with (list . "service-name"). Empty
otel.endpoint renders nothing, so the service exports no spans. */}}
{{- define "ace.otelEnv" -}}
{{- $root := index . 0 -}}
{{- if $root.Values.otel.endpoint }}
- name: OTEL_SERVICE_NAME
  value: {{ index . 1 | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ $root.Values.otel.endpoint | quote }}
{{- end }}
{{- end -}}

{{/* An init container that waits until Postgres and Temporal accept TCP connections.
Under python.reload the file watcher does not restart a process that exits, so the API
and the worker must not start before their dependencies listen. */}}
{{- define "ace.waitForDeps" -}}
- name: wait-for-deps
  {{- include "ace.pythonImage" . | nindent 2 }}
  command:
    - python
    - -c
    - |
      import socket, sys, time
      for target in sys.argv[1:]:
          host, port = target.rsplit(":", 1)
          while True:
              try:
                  socket.create_connection((host, int(port)), timeout=2).close()
                  break
              except OSError:
                  print("waiting for", target, flush=True)
                  time.sleep(2)
    - {{ printf "%s:%v" (include "ace.host" (list . .Values.postgres.serviceName)) .Values.postgres.port | quote }}
    - {{ printf "%s:%v" (include "ace.host" (list . .Values.temporal.serviceName)) .Values.temporal.port | quote }}
{{- end -}}
