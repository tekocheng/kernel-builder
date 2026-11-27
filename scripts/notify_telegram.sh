#!/usr/bin/env bash
# Send a Telegram message about a finished build job. A successful build also sends its zip.
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
zip_path="$(find "${release}" -maxdepth 1 -name '*.zip' -print 2>/dev/null | head -n1)"
zip_name="${zip_path##*/}"
# The Bot API accepts uploads up to 50 MB. Stay a little below it.
max_zip_bytes="${MAX_ZIP_BYTES:-51380224}"

text="${icon} ${word}: ${DEVICE:-?} / ${SOURCE:-?} / ${MANAGER:-?} (r${RUN_NUMBER:-?})"
[[ -n "${uname_line}" ]] && text+=$'\n'"uname: ${uname_line}"
[[ -n "${zip_name}" ]] && text+=$'\n'"zip: ${zip_name}"
[[ -n "${RUN_URL:-}" ]] && text+=$'\n'"${RUN_URL}"

# The token goes through curl's config on stdin so it never appears in the process list.
api() {
  printf 'url = "https://api.telegram.org/bot%s/%s"\n' "${TELEGRAM_BOT_TOKEN}" "$1"
}

send_message() {
  curl -fsS --max-time 20 --config - \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    --data-urlencode "disable_web_page_preview=true" \
    <<< "$(api sendMessage)" > /dev/null
}

send_document() {
  local caption="${text}" sum=""
  if [[ -f "${zip_path}.sha256" ]]; then
    sum="$(awk '{print $1; exit}' "${zip_path}.sha256")"
    [[ -n "${sum}" ]] && caption+=$'\n'"sha256: ${sum}"
  fi
  # --form-string keeps a caption that starts with @ or < from being read as a file or a value.
  # HTTP/1.1 and no Expect header avoid stalled large uploads. A stalled transfer is dropped after
  # 90 seconds below 10 KB/s instead of waiting for the full time limit. The stats line holds no secret.
  curl -fsS --http1.1 -H 'Expect:' --connect-timeout 20 --max-time 420 \
    --speed-limit 10240 --speed-time 90 --config - \
    --form-string "chat_id=${TELEGRAM_CHAT_ID}" \
    --form-string "caption=${caption:0:1000}" \
    -F "document=@${zip_path}" \
    -o /dev/null \
    --write-out 'Telegram upload: http=%{http_code} sent=%{size_upload}B speed=%{speed_upload}B/s time=%{time_total}s\n' \
    <<< "$(api sendDocument)"
}

if [[ "${JOB_STATUS:-unknown}" == "success" && "${SEND_ZIP:-true}" != "false" && -s "${zip_path}" ]]; then
  size="$(stat -c%s "${zip_path}")"
  if (( size <= max_zip_bytes )); then
    if send_document; then
      echo "Telegram notification sent with ${zip_name}"
      exit 0
    fi
    echo "::warning::Telegram zip upload failed; sending the text message instead"
  else
    text+=$'\n'"The zip is $(( size / 1048576 )) MB, too large for Telegram. Download it from the run page."
  fi
fi

if send_message; then
  echo "Telegram notification sent"
else
  echo "::warning::Telegram notification failed"
fi
exit 0
