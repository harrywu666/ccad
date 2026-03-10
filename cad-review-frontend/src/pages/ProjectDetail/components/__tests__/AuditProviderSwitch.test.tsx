import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { AuditProviderSelector } from '../AuditProgressDialog';

describe('AuditProviderSwitch', () => {
  it('allows selecting kimi sdk or codex sdk before starting audit', () => {
    const onChange = vi.fn();

    render(
      <AuditProviderSelector
        value="kimi_sdk"
        onChange={onChange}
      />,
    );

    expect(screen.getByLabelText(/Codex SDK/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Codex SDK/));

    expect(onChange).toHaveBeenCalledWith('codex_sdk');
  });
});
