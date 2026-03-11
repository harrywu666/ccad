import { render, screen } from '@testing-library/react';
import FindingStatusBadge from '../FindingStatusBadge';

describe('FindingStatusBadge', () => {
  it('renders needs_review badge', () => {
    render(<FindingStatusBadge status="needs_review" reviewRound={3} sourceAgent="dimension_review_agent" />);

    expect(screen.getByText('待人工确认')).toBeInTheDocument();
    expect(screen.getByText('已补图复核')).toBeInTheDocument();
    expect(screen.queryByText('尺寸审查Agent')).not.toBeInTheDocument();
  });

  it('renders confirmed badge without review round hint', () => {
    render(<FindingStatusBadge status="confirmed" reviewRound={1} sourceAgent="relationship_review_agent" />);

    expect(screen.getByText('已确认')).toBeInTheDocument();
    expect(screen.queryByText('已补图复核')).not.toBeInTheDocument();
  });

  it('stays empty when legacy data has no structured status', () => {
    const { container } = render(<FindingStatusBadge status={null} reviewRound={1} sourceAgent={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
