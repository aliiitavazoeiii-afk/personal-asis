package com.personalassist.app

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import org.json.JSONArray

internal object ReminderScheduler {
    private const val PREF = "reminders"
    private const val KEY = "scheduled"
    private fun pending(context: Context, id: String, title: String): PendingIntent {
        val intent = Intent(context, ReminderReceiver::class.java).apply {
            action = "com.personalassist.app.REMINDER"
            data = android.net.Uri.parse("personalassist://reminder/$id")
            putExtra("reminder_id", id)
            putExtra("reminder_title", title)
        }
        return PendingIntent.getBroadcast(context, id.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    fun sync(context: Context, json: String) {
        val list = JSONArray(json)
        if (list.length() > 100) return
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val old = JSONArray(prefs.getString(KEY, "[]"))
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        for (i in 0 until old.length()) {
            val o = old.optJSONObject(i) ?: continue
            manager.cancel(pending(context, o.optString("id"), o.optString("title")))
        }
        // Store before scheduling so a reboot receiver can recover reminders.
        prefs.edit().putString(KEY, json).apply()
        schedule(context, list)
    }
    fun restore(context: Context) {
        val json = context.getSharedPreferences(PREF, Context.MODE_PRIVATE).getString(KEY, "[]") ?: "[]"
        schedule(context, JSONArray(json))
    }
    private fun schedule(context: Context, list: JSONArray) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        for (i in 0 until list.length()) {
            val o = list.optJSONObject(i) ?: continue
            val due = o.optLong("epoch")
            val id = o.optString("id")
            if (id.isBlank() || due <= System.currentTimeMillis()) continue
            val intent = pending(context, id, o.optString("title", "یادآوری"))
            // Inexact Android-compatible alarm: Doze/battery policies may delay delivery.
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, due, intent)
        }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "personal-assist-reminders"
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(channelId, "یادآوری‌ها", NotificationManager.IMPORTANCE_HIGH))
        val title = intent.getStringExtra("reminder_title") ?: "یادآوری"
        val open = Intent(context, MainActivity::class.java)
        val tap = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle("Personal Assist")
            .setContentText(title)
            .setStyle(NotificationCompat.BigTextStyle().bigText(title))
            .setContentIntent(tap)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        nm.notify(intent.getStringExtra("reminder_id")?.hashCode() ?: 0, notification)
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED) ReminderScheduler.restore(context)
    }
}
