// Orbit booking confirmations, one email each: a flight or stay becomes a calendar event with the user as a guest
// (Google's invitation email carries the booking details); a shopping order, which has no event, is a plain email.
// Runs in the demo Google account (script.google.com), called by Orbit's backend (backend/notify.py) after you
// approve a booking. Setup:
//   1. script.google.com > New project > paste this file over Code.gs > save.
//   2. Project Settings (gear) > Script properties > add ORBIT_SECRET = the ORBIT_NOTIFY_SECRET from Orbit's .env.
//      Also tick "Show appsscript.json" and set "timeZone": "Asia/Kolkata".
//   3. Deploy > New deployment > type Web app > Execute as: Me, Who has access: Anyone > Deploy > allow access.
//   4. Copy the Web app URL into Orbit's .env as ORBIT_NOTIFY_URL. Restart the backend.
// "Anyone" can reach the URL, but without the secret it does nothing.
function doPost(e) {
  try {
    var b = JSON.parse(e.postData.contents);
    var secret = PropertiesService.getScriptProperties().getProperty("ORBIT_SECRET");
    if (!secret || b.secret !== secret) return reply({ ok: false, error: "wrong secret" });
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(b.to || "")) return reply({ ok: false, error: "not an email address" });
    var event = null;
    if (!b.event) {
      MailApp.sendEmail({ to: b.to, name: "Orbit", subject: String(b.subject).slice(0, 200), body: String(b.body).slice(0, 5000) });
    } else {
      var cal = CalendarApp.getDefaultCalendar();
      var options = { description: String(b.body).slice(0, 5000), location: b.event.location || "", guests: b.to, sendInvites: true };
      var start = new Date(b.event.start), end = new Date(b.event.end);
      event = b.event.all_day
        ? cal.createAllDayEvent(b.event.title, start, end, options)
        : cal.createEvent(b.event.title, start, end, options);
    }
    return reply({ ok: true, event: event ? event.getId() : null });
  } catch (err) {
    return reply({ ok: false, error: String(err).slice(0, 200) });
  }
}

function reply(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
