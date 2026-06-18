export function trackPilotEvent(eventName: string, properties: Record<string, any> = {}) {
  // In a real scenario, this would send data to Mixpanel, PostHog, or Amplitude.
  // For the pilot, we console log the metrics or send to a telemetry endpoint.
  console.log(`[Pilot Metric] ${eventName}`, properties)
}
