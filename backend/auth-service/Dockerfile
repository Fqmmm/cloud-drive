FROM maven:3.9.9-eclipse-temurin-17@sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc AS build
WORKDIR /build
COPY auth-service/pom.xml pom.xml
COPY auth-service/src src
RUN mvn -B verify

FROM eclipse-temurin:17-jre@sha256:0b6521287f850ec1c4b31c9074c5a1ae1d67c5922c3fefd21065c7c32e244d4a
WORKDIR /app
COPY --from=build /build/target/auth-service.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
