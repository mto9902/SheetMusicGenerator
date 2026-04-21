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
    <div className="field__header">
      <h3 className="field__label">{label}</h3>
      {hint ? <p className="field__hint">{hint}</p> : null}
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
    <section className="field">
      {renderCopy(label, hint)}
      <div className="pill-grid">
        {options.map((option) => {
          const isActive = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              className={`pill ${isActive ? "pill--active" : ""}`}
              onClick={() => onChange(option.value)}
            >
              <span>{option.label}</span>
              {option.hint ? <small>{option.hint}</small> : null}
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
    <section className="field">
      {renderCopy(label, hint)}
      <div className="pill-grid">
        {options.map((option) => {
          const isActive = values.includes(option.value);
          return (
            <button
              key={String(option.value)}
              type="button"
              className={`pill ${isActive ? "pill--active" : ""}`}
              onClick={() => onToggle(option.value)}
            >
              <span>{option.label}</span>
              {option.hint ? <small>{option.hint}</small> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
