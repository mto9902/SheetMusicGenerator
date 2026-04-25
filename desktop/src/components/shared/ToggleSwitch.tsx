interface ToggleSwitchProps {
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
}

export function ToggleSwitch({ value, onChange, label }: ToggleSwitchProps) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        className={`toggle-track ${value ? 'on' : ''}`}
        onClick={() => onChange(!value)}
      >
        <div className="toggle-thumb" />
      </button>
      <span className="text-[13px] text-[#1C1C1E]" style={{ fontFamily: 'Inter, sans-serif' }}>
        {label}
      </span>
    </div>
  );
}
