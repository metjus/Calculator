import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MapPin } from "lucide-react";
import { useEffect, useRef } from "react";
import type { AreaSuggestion } from "../lib/api";
import { useTheme } from "../lib/theme";

const ACCENT = { light: "#0b6e72", dark: "#4fb8b3" }; // --accent in tokens.css

type Props = { tileUrl: string; area: AreaSuggestion | null; mode: "radius" | "region"; radiusKm: number };

/** Read-only preview of the search area: a circle for a radius search, the bounding box for a whole region. */
export function MapPreview({ tileUrl, area, mode, radiusKm }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!box.current || !area) return;
    const instance = L.map(box.current, { zoomControl: true, scrollWheelZoom: false, attributionControl: true }).setView([area.lat, area.lon], 11);
    L.tileLayer(tileUrl, { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(instance);
    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
      layer.current = null;
    };
    // Created when the container appears; area changes are drawn by the effect below.
  }, [tileUrl, Boolean(area)]);

  useEffect(() => {
    const instance = map.current;
    const group = layer.current;
    if (!instance || !group || !area) return;
    group.clearLayers();
    // Leaflet needs literal colours; child effects run before ThemeProvider updates <html>, so don't read the CSS var.
    const accent = ACCENT[theme];
    const style = { color: accent, weight: 2, fillColor: accent, fillOpacity: 0.12 };
    L.circleMarker([area.lat, area.lon], { radius: 5, color: accent, weight: 2, fillColor: accent, fillOpacity: 1 }).addTo(group);
    if (mode === "region" && area.bbox) {
      const [minLon, minLat, maxLon, maxLat] = area.bbox;
      const bounds = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
      L.rectangle(bounds, { ...style, dashArray: "6 6" }).addTo(group);
      instance.fitBounds(bounds, { padding: [16, 16] });
    } else {
      L.circle([area.lat, area.lon], { ...style, radius: radiusKm * 1000 }).addTo(group);
      // Circle.getBounds() needs a rendered layer; derive the box from the centre instead.
      instance.fitBounds(L.latLng(area.lat, area.lon).toBounds(radiusKm * 2000), { padding: [16, 16] });
    }
  }, [area, mode, radiusKm, theme]);

  if (!area) {
    return (
      <div className="map map-empty">
        <MapPin size={22} aria-hidden />
        <span>Pick a country and a town to see the search area.</span>
      </div>
    );
  }
  return (
    <div
      className="map"
      ref={box}
      role="img"
      aria-label={mode === "region" ? `Map of ${area.label}` : `Map: ${radiusKm} km around ${area.label}`}
    />
  );
}
