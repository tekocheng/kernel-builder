#!/usr/bin/env bash
# Send a Telegram message about a finished build job.
# Does nothing when the bot secrets are not set, and never fails the job.
set -uo pipefail

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set"
  exit 0
fi

case "${JOB_STATUS:-unknown}" in
  success) icon="✅"; word="Build succeeded" ;;
  cancelled) icon="⚠️"; word="Build cancelled" ;;
  *) icon="❌"; word="Build failed" ;;
esac

release="${RELEASE_DIR:-release}"
uname_line="$(head -n1 "${release}/kernel-release.txt" 2>/dev/null || true)"
zip_name="$(find "${release}" -maxdepth 1 -name '*.zip' -printf '%f\n' 2>/dev/null | head -n1)"

text="${icon} ${word}: ${DEVICE:-?} / ${SOURCE:-?} / ${MANAGER:-?} (r${RUN_NUMBER:-?})"
[[ -n "${uname_line}" ]] && text+=$'\n'"uname: ${uname_line}"
[[ -n "${zip_name}" ]] && text+=$'\n'"zip: ${zip_name}"
[[ -n "${RUN_URL:-}" ]] && text+=$'\n'"${RUN_URL}"

# The token goes through curl's config on stdin so it never appears in the process list.
if curl -fsS --max-time 20 --config - \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    --data-urlencode "disable_web_page_preview=true" \
    <<< "url = \"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage\"" > /dev/null; then
  echo "Telegram notification sent"
else
  echo "::warning::Telegram notification failed"
fi
exit 0
