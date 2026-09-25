const normalizeCitationList = (value: unknown): any[] => {
	if (Array.isArray(value)) {
		return value;
	}

	if (value === null || value === undefined) {
		return [];
	}

	return [value];
};

export const getCitationDocuments = (citation: any): any[] => {
	return normalizeCitationList(citation?.document ?? citation?.documents);
};

export const getCitationMetadata = (citation: any): any[] => {
	return normalizeCitationList(citation?.metadata);
};

export const getCitationDistances = (citation: any): any[] => {
	return normalizeCitationList(citation?.distances);
};

const getMetadataFallbackDocument = (metadata: any): string => {
	if (!metadata || typeof metadata !== 'object') {
		return '';
	}

	const candidates = [
		metadata.content,
		metadata.snippet,
		metadata.text,
		metadata.summary,
		metadata.description
	];
	for (const candidate of candidates) {
		if (typeof candidate === 'string' && candidate.trim()) {
			return candidate;
		}
	}

	return '';
};

export const getCitationEntries = (citation: any) => {
	const documents = getCitationDocuments(citation);
	const metadata = getCitationMetadata(citation);
	const distances = getCitationDistances(citation);

	const entryCount = Math.max(
		documents.length,
		metadata.length,
		distances.length,
		citation?.source ? 1 : 0
	);

	return Array.from({ length: entryCount }, (_, index) => {
		const document = documents[index];
		const documentText = typeof document === 'string' ? document : `${document ?? ''}`;

		return {
			document: documentText.trim() ? documentText : getMetadataFallbackDocument(metadata[index]),
			metadata: metadata[index],
			distance: distances[index]
		};
	});
};

const isWebUrl = (value: unknown): value is string =>
	typeof value === 'string' && (value.startsWith('http://') || value.startsWith('https://'));

/**
 * What a citation is numbered by: the document's own source (the page URL for
 * web results), else the id of the source it came with. The backend numbers
 * the model's <source id="n"> blocks by the same key (_citation_key in
 * backend/open_webui/utils/middleware.py), so [n] in an answer is entry n of
 * getCitationList.
 */
export const getCitationKey = (source: any, metadata: any): string =>
	String(metadata?.source || source?.source?.id || 'N/A');

export type CitationGroup = {
	id: string;
	/** Label for inline citation chips and the source list. */
	title: string;
	source: any;
	document: string[];
	metadata: any[];
	distances: number[];
};

/** A message's sources grouped per citation, in the order [1], [2], ... refer to. */
export const getCitationList = (sources: unknown): CitationGroup[] => {
	const citations: CitationGroup[] = [];
	for (const source of Array.isArray(sources) ? sources : []) {
		if (!source || typeof source !== 'object' || Object.keys(source).length === 0) {
			continue;
		}

		getCitationEntries(source).forEach(({ document, metadata, distance }) => {
			const id = getCitationKey(source, metadata);
			const existing = citations.find((item) => item.id === id);
			if (existing) {
				existing.document.push(document);
				existing.metadata.push(metadata);
				if (distance !== undefined) existing.distances.push(distance);
				return;
			}

			let citationSource = source?.source;
			if (metadata?.name) {
				citationSource = { ...citationSource, name: metadata.name };
			}
			if (isWebUrl(id)) {
				citationSource = { ...citationSource, name: id, url: id };
			}
			citations.push({
				id,
				title: String(
					metadata?.name ||
						(isWebUrl(metadata?.source) ? metadata.source : (source?.source?.name ?? id))
				),
				source: citationSource,
				document: [document],
				metadata: metadata ? [metadata] : [],
				distances: distance !== undefined ? [distance] : []
			});
		});
	}
	return citations;
};
