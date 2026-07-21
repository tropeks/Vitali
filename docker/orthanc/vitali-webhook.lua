-- Vitali — Orthanc → Vitali push webhook (E-012).
--
-- When a study finishes arriving and becomes "stable", POST its Orthanc id to
-- the Vitali webhook so DicomStudy.orthanc_study_id is backfilled immediately
-- (the Celery poller stays as the catch-up/replay path). The webhook URL and
-- shared secret are injected via the container environment; if the URL is unset
-- the hook is a no-op, so the same image is safe in stacks without Vitali.

function OnStableStudy(studyId, tags, metadata)
   local url = os.getenv('VITALI_WEBHOOK_URL')
   if url == nil or url == '' then
      return
   end

   local secret = os.getenv('VITALI_WEBHOOK_SECRET') or ''
   local body = DumpJson({ ['orthanc_study_id'] = studyId }, true)
   local headers = {
      ['Content-Type'] = 'application/json',
      ['X-Orthanc-Webhook-Secret'] = secret
   }

   -- Never let a webhook failure abort Orthanc's stable-study processing.
   local ok, err = pcall(function()
      HttpPost(url, body, headers)
   end)
   if not ok then
      print('Vitali webhook POST failed for study ' .. studyId .. ': ' .. tostring(err))
   end
end
