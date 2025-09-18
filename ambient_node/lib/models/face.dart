class Face {
  final String id;
  final String name;
  final double confidence;
  const Face({required this.id, required this.name, required this.confidence});
  Face copyWith({String? id, String? name, double? confidence}) => Face(
      id: id ?? this.id,
      name: name ?? this.name,
      confidence: confidence ?? this.confidence);
}
