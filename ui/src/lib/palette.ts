export interface PaletteItem {
  group: string;
  label: string;
  icon: string;
  hint?: string;
  run: () => void;
}
