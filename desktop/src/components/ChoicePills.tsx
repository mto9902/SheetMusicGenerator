type PillValue = string | number;

export type ChoiceOption<T extends PillValue> = {
  value: T;
  label: string;
  hint?: string;
};

type SharedProps = {
  label: string;
  hint?: string;
};

type ChoicePillsProps<T extends PillValue> = SharedProps & {
  options: ChoiceOption<T>[];
  value: T;
  onChange: (value: T) => void;
};

type MultiChoicePillsProps<T extends PillValue> = SharedProps & {
  options: ChoiceOption<T>[];
  values: T[];
  onToggle: (value: T) => void;
};

function renderCopy(label: string, hint?: string) {
  return (
    <div className="mb-2.5">
      <h3 className="text-sm font-semibold text-[#1C1C1E]">{label}</h3>
      {hint ? <p className="text-xs text-[#8E8E93] mt-0.5">{hint}</p> : null}
    </div>
  );
}

export function ChoicePills<T extends PillValue>({
  label,
  hint,
  options,
  value,
  onChange,
}: ChoicePillsProps<T>) {
  return (
    <section className="mb-5">
      {renderCopy(label, hint)}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const isActive = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              className={`pill ${isActive ? 'pill--active' : ''}`}
              onClick={() => onChange(option.value)}
            >
              <span className="text-sm font-medium">{option.label}</span>
              {option.hint ? <small className="text-[11px]">{option.hint}</small> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function MultiChoicePills<T extends PillValue>({
  label,
  hint,
  options,
  values,
  onToggle,
}: MultiChoicePillsProps<T>) {
  return (
    <section className="mb-5">
      {renderCopy(label, hint)}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const isActive = values.includes(option.value);
          return (
            <button
              key={String(option.value)}
              type="button"
              className={`pill ${isActive ? 'pill--active' : ''}`}
              onClick={() => onToggle(option.value)}
            >
              <span className="text-sm font-medium">{option.label}</span>
              {option.hint ? <small className="text-[11px]">{option.hint}</small> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
