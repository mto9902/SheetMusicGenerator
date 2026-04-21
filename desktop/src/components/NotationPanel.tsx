type Props = {
  svg: string;
  scale?: number;
};

export function NotationPanel({ svg, scale = 1 }: Props) {
  if (!svg) {
    return (
      <div className="notation-frame notation-frame--empty">
        <p>Notation preview unavailable.</p>
      </div>
    );
  }

  return (
    <div className="notation-frame">
      <div className="notation-scroll">
        <div
          className="notation-artwork"
          style={{ width: `${Math.max(0.85, scale) * 100}%` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}
