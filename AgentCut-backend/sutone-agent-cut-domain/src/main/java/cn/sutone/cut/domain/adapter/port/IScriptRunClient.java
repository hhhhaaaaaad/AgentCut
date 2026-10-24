package cn.sutone.cut.domain.adapter.port;

/** Prepared-input transport. Never retries POST or creates a replacement runId. */
public interface IScriptRunClient {
    String submit(String snapshotJson);
    String status(String runId, String token);

    final class SubmissionException extends RuntimeException {
        private final boolean uncertain;
        public SubmissionException(boolean uncertain) {
            super(uncertain ? "SUBMISSION_UNCERTAIN" : "SUBMISSION_REJECTED");
            this.uncertain = uncertain;
        }
        public boolean uncertain() { return uncertain; }
    }
}
